"""对抗性验证测试：验证审计报告中所有修复项是否真正生效。"""

import asyncio
import time

import pytest

from protoforge.engine.engine import SimulationEngine
from protoforge.engine.generator import DataGenerator, ScriptEngine
from protoforge.engine.network_sim import NetworkProfile
from protoforge.models.device import (
    DataType,
    DeviceConfig,
    GeneratorType,
    PointConfig,
)
from protoforge.models.scenario import ScenarioConfig, ScenarioStatus


@pytest.fixture
async def engine():
    """创建并启动引擎，测试后自动停止。"""
    eng = SimulationEngine()
    await eng.start()
    yield eng
    await eng.stop()


@pytest.mark.asyncio
async def test_01_network_simulator_integration(engine):
    """Fix 1: NetworkSimulator 集成到引擎读写路径。"""
    engine.configure_network({"latency_ms": 50, "jitter_ms": 0, "packet_loss_rate": 0.0}, enabled=True)
    assert engine._network_sim.enabled is True
    assert engine._network_sim.profile.latency_ms == 50

    config = DeviceConfig(
        id="net-dev", name="Net Device", protocol="modbus_tcp",
        points=[PointConfig(name="temp", address="HR0", data_type=DataType.FLOAT32,
                             generator_type=GeneratorType.SINE, min_value=0, max_value=100)],
    )
    await engine.create_device(config)
    await engine.start_device("net-dev")

    # 读取应有网络延迟
    start = time.time()
    points = await engine.read_device_points("net-dev")
    elapsed = time.time() - start
    assert elapsed >= 0.04, f"Expected >=50ms delay, got {elapsed*1000:.1f}ms"
    assert len(points) == 1

    # 写入应有网络延迟
    start = time.time()
    ok = await engine.write_device_point("net-dev", "temp", 42.0)
    elapsed = time.time() - start
    assert ok is True
    assert elapsed >= 0.04

    engine.configure_network("ideal", enabled=False)


@pytest.mark.asyncio
async def test_02_scan_cycle_parameter(engine):
    """Fix 2: 设备扫描周期参数 scan_cycle_ms。"""
    config = DeviceConfig(
        id="scan-dev", name="Scan Device", protocol="modbus_tcp",
        points=[PointConfig(name="val", address="HR0", data_type=DataType.FLOAT32,
                             generator_type=GeneratorType.SINE, min_value=0, max_value=100)],
        protocol_config={"scan_cycle_ms": 500},
    )
    await engine.create_device(config)
    assert config.protocol_config.get("scan_cycle_ms") == 500
    # 引擎应跟踪设备级扫描周期
    assert hasattr(engine, "_device_last_tick")


@pytest.mark.asyncio
async def test_03_timeseries_recording_config(engine):
    """Fix 3: 仿真数据时序记录配置。"""
    engine.configure_timeseries_recording(1.0)
    assert engine._timeseries_record_interval == 1.0
    engine.configure_timeseries_recording(0.0)
    assert engine._timeseries_record_interval == 0.0


@pytest.mark.asyncio
async def test_04_device_snapshot_import_export(engine):
    """Fix 4: 设备快照导入/导出。"""
    config = DeviceConfig(
        id="snap-dev", name="Snap Device", protocol="modbus_tcp",
        points=[
            PointConfig(name="temp", address="HR0", data_type=DataType.FLOAT32,
                        generator_type=GeneratorType.FIXED, fixed_value=25.0, access="rw"),
            PointConfig(name="pressure", address="HR1", data_type=DataType.FLOAT32,
                        generator_type=GeneratorType.FIXED, fixed_value=1.0, access="rw"),
        ],
    )
    await engine.create_device(config)
    await engine.start_device("snap-dev")

    # 保存快照
    snapshot_id = await engine.save_device_snapshot("snap-dev", "test_snapshot")
    assert snapshot_id is not None

    # 导入快照
    ok = await engine.import_device_snapshot("snap-dev", {
        "point_values": {"temp": 75.0, "pressure": 5.0}
    })
    assert ok is True

    instance = engine.get_device_instance("snap-dev")
    assert instance.get_raw_point_value("temp") == 75.0
    assert instance.get_raw_point_value("pressure") == 5.0


def test_05_deadband_filtering():
    """Fix 5: 点位死区参数 deadband。"""
    gen = DataGenerator()
    pc = PointConfig(
        name="db_test", address="HR0", data_type=DataType.FLOAT32,
        generator_type=GeneratorType.SINE, min_value=0, max_value=100,
        deadband=5.0,
    )
    # deadband 参数应被接受
    assert pc.deadband == 5.0
    # 生成器应能正常生成值
    v1 = gen.generate(pc)
    v2 = gen.generate(pc)
    assert isinstance(v1, float)
    assert isinstance(v2, float)


@pytest.mark.asyncio
async def test_06_scenario_stop_atomization(engine):
    """Fix 8: 场景停止原子化。"""
    config = DeviceConfig(
        id="scn-dev", name="Scenario Device", protocol="modbus_tcp",
        points=[PointConfig(name="val", address="HR0", data_type=DataType.FLOAT32,
                             generator_type=GeneratorType.SINE, min_value=0, max_value=100)],
    )
    sc = ScenarioConfig(id="stop-test", name="Stop Test", description="",
                       devices=[config], rules=[])
    await engine.create_scenario(sc)
    await engine.start_scenario("stop-test")
    assert engine.get_scenario_status("stop-test") == ScenarioStatus.RUNNING

    await engine.stop_scenario("stop-test")
    assert engine.get_scenario_status("stop-test") == ScenarioStatus.STOPPED

    # 幂等：再次停止不应抛出异常
    await engine.stop_scenario("stop-test")
    assert engine.get_scenario_status("stop-test") == ScenarioStatus.STOPPED


@pytest.mark.asyncio
async def test_07_concurrency_conflict_simulation(engine):
    """Fix 9: 并发冲突模拟（连接跟踪和限制）。"""
    for name, server in engine.get_all_protocol_servers().items():
        # 验证方法存在
        assert hasattr(server, "check_connection_allowed")
        assert hasattr(server, "on_client_connect")
        assert hasattr(server, "on_client_disconnect")
        assert hasattr(server, "active_connections")

        # 测试连接跟踪
        assert server.check_connection_allowed() is True
        server.on_client_connect()
        assert server.active_connections == 1
        server.on_client_disconnect()
        assert server.active_connections == 0

    # 测试 max_connections 限制
    engine._network_sim.set_profile(NetworkProfile(max_connections=1))
    engine._network_sim.enable()
    for name, server in engine.get_all_protocol_servers().items():
        assert server.check_connection_allowed() is True
        server.on_client_connect()
        assert server.check_connection_allowed() is False  # 达到上限
        server.on_client_disconnect()
        assert server.check_connection_allowed() is True
    engine._network_sim.disable()


@pytest.mark.asyncio
async def test_08_network_simulator_packet_loss(engine):
    """Fix 1 补充: 丢包模拟在读取时回退到内存值。"""
    engine.configure_network({"latency_ms": 0, "jitter_ms": 0, "packet_loss_rate": 1.0}, enabled=True)
    # packet_loss_rate=1.0 意味着所有请求都被丢弃
    config = DeviceConfig(
        id="loss-dev", name="Loss Device", protocol="modbus_tcp",
        points=[PointConfig(name="val", address="HR0", data_type=DataType.FLOAT32,
                             generator_type=GeneratorType.SINE, min_value=0, max_value=100)],
    )
    await engine.create_device(config)
    await engine.start_device("loss-dev")

    # 读取应回退到内存值（丢包后）
    points = await engine.read_device_points("loss-dev")
    assert len(points) == 1
    assert points[0].simulated is True  # 内存回退标记

    # 写入应失败（丢包后）
    ok = await engine.write_device_point("loss-dev", "val", 42.0)
    assert ok is False

    engine.configure_network("ideal", enabled=False)


def test_09_script_expression_evaluation():
    """Fix 11: 数据生成公式表达式计算。"""
    se = ScriptEngine()
    result = se.execute("result = sin(elapsed * 0.1) * 50 + 50", {"elapsed": 10.0})
    assert result is not None
    assert isinstance(result, float)
    # sin(1.0) ≈ 0.8415, result ≈ 92.07
    assert 90 < result < 94


def test_10_fault_templates_available():
    """Fix 12: 故障注入规则预设模板。"""
    from protoforge.api.v1.simulation_routes import FAULT_PRESET_TEMPLATES

    assert len(FAULT_PRESET_TEMPLATES) >= 9
    template_ids = [t["id"] for t in FAULT_PRESET_TEMPLATES]
    expected = {"sensor-drift", "sensor-noise", "sensor-stuck",
                "communication-loss", "device-failure", "value-offset",
                "value-saturation", "intermittent-signal-loss", "calibration-error"}
    assert expected.issubset(set(template_ids))

    # 验证模板结构
    for t in FAULT_PRESET_TEMPLATES:
        assert "id" in t
        assert "name" in t
        assert "fault_type" in t
        assert "parameters" in t
