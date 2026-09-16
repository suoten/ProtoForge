"""场景级协同联动集成测试.

验证 ``RuleType.COLLABORATION`` 规则通过 ``Scenario`` → ``DeviceCollaboration``
→ ``DeviceInstance`` 的完整路径。区别于 ``test_collaboration.py``（使用内存
FakeDeviceStore），本测试使用真实的 ``DeviceInstance`` 对象，覆盖：

1. 协同规则在场景启动时被转换并注册到协同引擎
2. 源点位满足条件 → 链式动作写入目标设备 → DeviceInstance 状态更新
3. 多动作链（set + delay + increment）
4. toggle 动作通过场景路径
5. cooldown 在场景路径下生效
6. disabled 规则不触发
7. 无 on_write_point 回调时回退到 DeviceInstance 内存写入

设备状态机要求 RUN 状态才视为 ONLINE（可读可写），因此 ``min_startup_time=0``
使设备在首次 tick 后立即进入 RUN。
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("PROTOFORGE_DB_PATH", "sqlite:///./data/test_collab_scenario.db")

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


def _temp_sensor(temp: float = 75.0) -> DeviceInstance:
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
                fixed_value=temp,
                access="rw",
            ),
        ],
    )
    return DeviceInstance(cfg, _gen())


def _fan(speed: float = 0.0) -> DeviceInstance:
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
                fixed_value=speed,
                access="rw",
            ),
            PointConfig(
                name="running",
                address="30",
                data_type=DataType.BOOL,
                generator_type=GeneratorType.FIXED,
                fixed_value=False,
                access="rw",
            ),
        ],
    )
    return DeviceInstance(cfg, _gen())


async def _bring_online(*devices: DeviceInstance) -> None:
    """启动设备并 tick 一次使其进入 RUN(ONLINE) 状态。"""
    for d in devices:
        d.start()
    for d in devices:
        await d.tick()


def _read_value(device: DeviceInstance, point: str):
    pv = device.read_point(point)
    return pv.value if pv else None


@pytest.mark.asyncio
async def test_collaboration_rule_triggers_set_action():
    """温度 > 80 → 风扇速度设为 100。"""
    sensor = _temp_sensor(75.0)
    fan = _fan(0.0)
    config = ScenarioConfig(
        id="scn-fan-control",
        name="Fan Control",
        devices=[],
        rules=[
            Rule(
                id="rule-fan",
                name="Auto fan on high temp",
                rule_type=RuleType.COLLABORATION,
                source_device_id="temp-sensor",
                source_point="temperature",
                condition={"operator": ">", "value": 80},
                actions=[
                    {"target_device_id": "fan", "target_point": "speed", "action_type": "set", "value": 100}
                ],
                cooldown=0.0,
            )
        ],
    )
    scenario = Scenario(config)
    scenario.add_device(sensor)
    scenario.add_device(fan)
    await _bring_online(sensor, fan)
    scenario.start()

    # 初始温度 75，不触发
    await scenario.tick()
    assert _read_value(fan, "speed") == 0.0

    # 升温到 85，触发
    await sensor.write_point("temperature", 85.0)
    await scenario.tick()
    assert _read_value(fan, "speed") == 100


@pytest.mark.asyncio
async def test_collaboration_multi_action_chain():
    """多动作链：set speed=100 → delay 0.05 → increment speed by 5。"""
    sensor = _temp_sensor(90.0)
    fan = _fan(0.0)
    config = ScenarioConfig(
        id="scn-chain",
        name="Chain",
        devices=[],
        rules=[
            Rule(
                id="rule-chain",
                name="Chain set delay increment",
                rule_type=RuleType.COLLABORATION,
                source_device_id="temp-sensor",
                source_point="temperature",
                condition={"operator": ">", "value": 80},
                actions=[
                    {"target_device_id": "fan", "target_point": "speed", "action_type": "set", "value": 100},
                    {"target_device_id": "fan", "target_point": "speed", "action_type": "delay", "delay": 0.05},
                    {"target_device_id": "fan", "target_point": "speed", "action_type": "increment", "value": 5},
                ],
            )
        ],
    )
    scenario = Scenario(config)
    scenario.add_device(sensor)
    scenario.add_device(fan)
    await _bring_online(sensor, fan)
    scenario.start()

    t0 = asyncio.get_event_loop().time()
    await scenario.tick()
    elapsed = asyncio.get_event_loop().time() - t0

    assert _read_value(fan, "speed") == 105  # 100 set, then +5 increment
    assert elapsed >= 0.04  # delay 生效


@pytest.mark.asyncio
async def test_collaboration_toggle_action():
    """toggle 动作：风扇 running False → True。"""
    sensor = _temp_sensor(85.0)
    fan = _fan(0.0)
    config = ScenarioConfig(
        id="scn-toggle",
        name="Toggle",
        devices=[],
        rules=[
            Rule(
                id="rule-toggle",
                name="Toggle fan running",
                rule_type=RuleType.COLLABORATION,
                source_device_id="temp-sensor",
                source_point="temperature",
                condition={"operator": ">", "value": 80},
                actions=[
                    {"target_device_id": "fan", "target_point": "running", "action_type": "toggle"}
                ],
            )
        ],
    )
    scenario = Scenario(config)
    scenario.add_device(sensor)
    scenario.add_device(fan)
    await _bring_online(sensor, fan)
    scenario.start()

    assert _read_value(fan, "running") is False
    await scenario.tick()
    assert _read_value(fan, "running") is True


@pytest.mark.asyncio
async def test_collaboration_cooldown_suppresses_retrigger():
    """cooldown=1.0：第一次触发后，1 秒内的后续 tick 不再重复触发。"""
    sensor = _temp_sensor(85.0)
    fan = _fan(0.0)
    config = ScenarioConfig(
        id="scn-cooldown",
        name="Cooldown",
        devices=[],
        rules=[
            Rule(
                id="rule-cd",
                name="Cooldown increment",
                rule_type=RuleType.COLLABORATION,
                source_device_id="temp-sensor",
                source_point="temperature",
                condition={"operator": ">", "value": 80},
                actions=[
                    {"target_device_id": "fan", "target_point": "speed", "action_type": "increment", "value": 10}
                ],
                cooldown=1.0,
            )
        ],
    )
    scenario = Scenario(config)
    scenario.add_device(sensor)
    scenario.add_device(fan)
    await _bring_online(sensor, fan)
    scenario.start()

    # 第一次触发：0 + 10 = 10
    await scenario.tick()
    assert _read_value(fan, "speed") == 10

    # cooldown 内再 tick：不应再 increment
    await scenario.tick()
    assert _read_value(fan, "speed") == 10

    # 等待 cooldown 过期
    await asyncio.sleep(1.05)
    await scenario.tick()
    assert _read_value(fan, "speed") == 20


@pytest.mark.asyncio
async def test_collaboration_disabled_rule_not_triggered():
    """enabled=False 的协同规则不触发。"""
    sensor = _temp_sensor(85.0)
    fan = _fan(0.0)
    config = ScenarioConfig(
        id="scn-disabled",
        name="Disabled",
        devices=[],
        rules=[
            Rule(
                id="rule-disabled",
                name="Disabled rule",
                rule_type=RuleType.COLLABORATION,
                source_device_id="temp-sensor",
                source_point="temperature",
                condition={"operator": ">", "value": 80},
                actions=[
                    {"target_device_id": "fan", "target_point": "speed", "action_type": "set", "value": 100}
                ],
                enabled=False,
            )
        ],
    )
    scenario = Scenario(config)
    scenario.add_device(sensor)
    scenario.add_device(fan)
    await _bring_online(sensor, fan)
    scenario.start()

    await scenario.tick()
    assert _read_value(fan, "speed") == 0.0  # 未触发


@pytest.mark.asyncio
async def test_collaboration_falls_back_to_memory_write():
    """未配置 on_write_point 回调时，协同写入回退到 DeviceInstance 内存。"""
    sensor = _temp_sensor(85.0)
    fan = _fan(0.0)
    config = ScenarioConfig(
        id="scn-nocallback",
        name="NoCallback",
        devices=[],
        rules=[
            Rule(
                id="rule-nocb",
                name="No callback set",
                rule_type=RuleType.COLLABORATION,
                source_device_id="temp-sensor",
                source_point="temperature",
                condition={"operator": ">", "value": 80},
                actions=[
                    {"target_device_id": "fan", "target_point": "speed", "action_type": "set", "value": 42}
                ],
            )
        ],
    )
    # Scenario(config) 不传 on_write_point → 回退到 device.write_point
    scenario = Scenario(config)
    scenario.add_device(sensor)
    scenario.add_device(fan)
    await _bring_online(sensor, fan)
    scenario.start()

    await scenario.tick()
    assert _read_value(fan, "speed") == 42


@pytest.mark.asyncio
async def test_collaboration_synthesizes_action_from_target_fields():
    """rule 无 actions 但有 target_device_id/target_point → 合成单个 set 动作。"""
    sensor = _temp_sensor(85.0)
    fan = _fan(0.0)
    config = ScenarioConfig(
        id="scn-synth",
        name="Synth",
        devices=[],
        rules=[
            Rule(
                id="rule-synth",
                name="Synth single set",
                rule_type=RuleType.COLLABORATION,
                source_device_id="temp-sensor",
                source_point="temperature",
                condition={"operator": ">", "value": 80},
                target_device_id="fan",
                target_point="speed",
                target_value=77,
            )
        ],
    )
    scenario = Scenario(config)
    scenario.add_device(sensor)
    scenario.add_device(fan)
    await _bring_online(sensor, fan)
    scenario.start()

    await scenario.tick()
    assert _read_value(fan, "speed") == 77


@pytest.mark.asyncio
async def test_collaboration_condition_not_met_no_action():
    """条件不满足时不触发动作。"""
    sensor = _temp_sensor(50.0)  # 低于 80
    fan = _fan(0.0)
    config = ScenarioConfig(
        id="scn-notmet",
        name="NotMet",
        devices=[],
        rules=[
            Rule(
                id="rule-notmet",
                name="Condition not met",
                rule_type=RuleType.COLLABORATION,
                source_device_id="temp-sensor",
                source_point="temperature",
                condition={"operator": ">", "value": 80},
                actions=[
                    {"target_device_id": "fan", "target_point": "speed", "action_type": "set", "value": 100}
                ],
            )
        ],
    )
    scenario = Scenario(config)
    scenario.add_device(sensor)
    scenario.add_device(fan)
    await _bring_online(sensor, fan)
    scenario.start()

    await scenario.tick()
    assert _read_value(fan, "speed") == 0.0
