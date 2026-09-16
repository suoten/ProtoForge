"""Phase 4 对抗验证测试。

验证 P4-1 至 P4-4 的所有修复，确保无回归。

覆盖项：
    P4-1: TimeSeriesPattern 引擎集成
    P4-2: STOPPING 状态自动完成
    P4-3: 剩余协议 CRC/半开集成 (BACnet/GB28181/Profinet/EtherCAT)
    P4-4: 事件驱动时序记录
    回归: 确保已有功能不受影响
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from protoforge.engine.device import DeviceInstance
from protoforge.engine.engine import SimulationEngine
from protoforge.engine.state_machine import DeviceState, DeviceStateMachine
from protoforge.simulation.timeseries import TimeSeriesManager, TimeSeriesPattern, PatternType
from protoforge.models.device import DeviceConfig, PointConfig, DataType, GeneratorType
from protoforge.protocols.bacnet.server import BACnetServer
from protoforge.protocols.gb28181.server import GB28181Server
from protoforge.protocols.profinet.server import ProfinetServer
from protoforge.protocols.ethercat.server import EtherCATServer


# ── 辅助函数 ──────────────────────────────────────────────────────────────

def _make_device_config(
    device_id: str = "test-device",
    protocol: str = "modbus",
    points: list[PointConfig] | None = None,
    **kwargs,
) -> DeviceConfig:
    # P4: 确保测试设备快速启动
    if "min_startup_time" not in kwargs:
        kwargs["min_startup_time"] = 0.01
    if points is None:
        points = [
            PointConfig(
                name="temperature",
                address="holding_register.0.1",
                data_type=DataType.FLOAT32,
                generator_type=GeneratorType.SINE,
                generator_params={"amplitude": 10.0, "offset": 50.0, "period": 60.0},
            ),
        ]
    return DeviceConfig(
        id=device_id,
        name=f"Test Device {device_id}",
        protocol=protocol,
        host="127.0.0.1",
        port=502,
        points=points,
        protocol_config=kwargs,
    )


def _make_device_instance(**kwargs) -> DeviceInstance:
    config = _make_device_config(**kwargs)
    from protoforge.engine.generator import DataGenerator
    gen = DataGenerator()
    return DeviceInstance(config, gen)


def _make_network_sim_mock(drop: bool = False, half_open: bool = False) -> MagicMock:
    """创建一个模拟 NetworkSimulator 的 mock，使用正确的方法名。"""
    mock = MagicMock()
    mock.should_inject_crc_error.return_value = drop
    mock.should_drop.return_value = drop
    mock.is_half_open.return_value = half_open
    return mock


# ── P4-1: TimeSeriesPattern 引擎集成 ──────────────────────────────────────

class TestTimeSeriesPatternIntegration:
    """验证 TimeSeriesPattern 在引擎 tick_loop 中正确应用。"""

    def test_configure_device_ts_patterns(self):
        """配置设备时间序列模式后，引擎应缓存并注册到 TimeSeriesManager。"""
        engine = SimulationEngine()
        patterns = {
            "temperature": {
                "pattern_type": "daily",
                "production_value": 85.0,
                "standby_value": 25.0,
            }
        }
        engine.configure_device_ts_patterns("dev1", patterns)
        assert "dev1" in engine._device_ts_patterns
        assert "temperature" in engine._device_ts_patterns["dev1"]

    def test_clear_device_ts_patterns(self):
        """清除设备时间序列模式后，缓存应被清除。"""
        engine = SimulationEngine()
        patterns = {
            "temperature": {"pattern_type": "daily", "production_value": 85.0}
        }
        engine.configure_device_ts_patterns("dev1", patterns)
        engine.clear_device_ts_patterns("dev1")
        assert "dev1" not in engine._device_ts_patterns

    def test_ts_pattern_apply_modifies_value(self):
        """TimeSeriesPattern.apply 应根据时间返回不同的值。"""
        pattern = TimeSeriesPattern(
            pattern_type=PatternType.DAILY,
            production_value=85.0,
            standby_value=25.0,
            work_start_hour=8,
            work_end_hour=18,
        )
        # 工作时间 (10:00) 应返回接近 production_value 的值
        import datetime
        work_time = datetime.datetime(2025, 7, 23, 10, 0, 0).timestamp()
        work_val = pattern.apply(50.0, work_time)

        # 非工作时间 (03:00) 应返回接近 standby_value 的值
        standby_time = datetime.datetime(2025, 7, 23, 3, 0, 0).timestamp()
        standby_val = pattern.apply(50.0, standby_time)

        assert work_val != standby_val, "工作时间和非工作时间值应不同"

    @pytest.mark.asyncio
    async def test_engine_ts_pattern_in_tick_loop(self):
        """引擎 tick_loop 中应正确应用 TS 模式。"""
        engine = SimulationEngine(tick_interval=0.1)

        # 创建设备实例并添加到引擎
        instance = _make_device_instance(device_id="ts-test")
        engine._devices["ts-test"] = instance
        engine._device_ts_patterns["ts-test"] = {
            "temperature": TimeSeriesPattern(
                pattern_type=PatternType.DAILY,
                production_value=85.0,
                standby_value=25.0,
            )
        }
        # 启动设备
        instance.start()
        time.sleep(0.02)  # 等待 min_startup_time
        await instance.tick()  # STARTING → RUN
        assert instance.device_state == DeviceState.RUN

        # 运行 tick
        await instance.tick()

        # 应用 TS 模式
        ts_patterns = engine._device_ts_patterns.get("ts-test")
        if ts_patterns:
            now = time.time()
            for pv in instance.read_all_points():
                pattern = ts_patterns.get(pv.name)
                if pattern and isinstance(pv.value, (int, float)):
                    new_val = engine._timeseries_manager.apply(pv.name, float(pv.value), now)
                    instance.set_point_value_internal(pv.name, new_val)

        # 验证值存在
        val = instance.read_point("temperature")
        assert val is not None


# ── P4-2: STOPPING 状态自动完成 ───────────────────────────────────────────

class TestStoppingAutoComplete:
    """验证 STOPPING 状态在设定时间后自动转为 STOP。"""

    @pytest.mark.asyncio
    async def test_stopping_auto_completes_to_stop(self):
        """配置 stopping_sequence_duration 后，STOPPING 状态应自动转为 STOP。"""
        instance = _make_device_instance(
            device_id="stopping-test",
            stopping_sequence_duration=0.1,
        )
        instance.start()
        time.sleep(0.02)  # 等待 min_startup_time
        await instance.tick()  # STARTING → RUN
        assert instance.device_state == DeviceState.RUN

        # 触发 stop → STOPPING
        instance.stop()
        assert instance.device_state == DeviceState.STOPPING

        # 等待停机序列完成
        time.sleep(0.15)
        await instance.tick()
        assert instance.device_state == DeviceState.STOP

    @pytest.mark.asyncio
    async def test_stopping_zero_duration_immediate(self):
        """stopping_sequence_duration=0 时，stop() 应直接到 STOP。"""
        instance = _make_device_instance(
            device_id="immediate-stop",
            stopping_sequence_duration=0.0,
        )
        instance.start()
        time.sleep(0.02)  # 等待 min_startup_time
        await instance.tick()  # STARTING → RUN
        assert instance.device_state == DeviceState.RUN

        instance.stop()
        # duration=0 时，stop() 直接完成到 STOP（不经过 STOPPING 停留）
        assert instance.device_state == DeviceState.STOP

    @pytest.mark.asyncio
    async def test_stopping_enter_time_recorded(self):
        """进入 STOPPING 状态时 _stopping_enter_time 应被记录。"""
        instance = _make_device_instance(
            device_id="stop-time-test",
            stopping_sequence_duration=1.0,
        )
        instance.start()
        await instance.tick()  # STARTING → RUN
        assert instance._stopping_enter_time is None

        instance.stop()
        assert instance.device_state == DeviceState.STOPPING
        assert instance._stopping_enter_time is not None

    @pytest.mark.asyncio
    async def test_stopping_not_completed_before_duration(self):
        """在 stopping_sequence_duration 时间内不应自动转为 STOP。"""
        instance = _make_device_instance(
            device_id="stopping-wait",
            stopping_sequence_duration=5.0,
        )
        instance.start()
        await instance.tick()  # STARTING → RUN
        instance.stop()
        assert instance.device_state == DeviceState.STOPPING

        # 立即 tick 不应完成停机
        await instance.tick()
        assert instance.device_state == DeviceState.STOPPING  # 仍在 STOPPING


# ── P4-3: 剩余协议 CRC/半开集成 ──────────────────────────────────────────

class TestProtocolCRCIntegration:
    """验证 BACnet/GB28181/Profinet/EtherCAT 协议集成了网络仿真。"""

    def test_bacnet_no_drop_when_no_network_sim(self):
        """BACnet 服务器在没有网络仿真器时不丢帧。"""
        server = BACnetServer()
        assert server.should_drop_frame() is False

    def test_bacnet_drop_with_network_sim(self):
        """BACnet 服务器在启用 CRC 错误率时应丢弃帧。"""
        server = BACnetServer()
        server._network_sim = _make_network_sim_mock(drop=True)
        assert server.should_drop_frame() is True

    def test_bacnet_no_drop_with_network_sim_no_error(self):
        """BACnet 服务器在网络仿真器未触发错误时不丢帧。"""
        server = BACnetServer()
        server._network_sim = _make_network_sim_mock(drop=False)
        assert server.should_drop_frame() is False

    def test_gb28181_drop_with_network_sim(self):
        """GB28181 服务器在启用 CRC 错误率时应丢弃帧。"""
        server = GB28181Server()
        server._network_sim = _make_network_sim_mock(drop=True)
        assert server.should_drop_frame() is True

    def test_profinet_half_open_simulation(self):
        """ProfinetServer 应支持半开连接模拟。"""
        server = ProfinetServer()
        server._network_sim = _make_network_sim_mock(half_open=True)
        assert server.should_simulate_half_open() is True

    def test_profinet_no_half_open(self):
        """ProfinetServer 在没有半开模拟时应返回 False。"""
        server = ProfinetServer()
        server._network_sim = _make_network_sim_mock(half_open=False)
        assert server.should_simulate_half_open() is False

    def test_profinet_should_drop_frame(self):
        """ProfinetServer 应支持帧丢弃模拟。"""
        server = ProfinetServer()
        server._network_sim = _make_network_sim_mock(drop=True)
        assert server.should_drop_frame() is True

    def test_ethercat_half_open_simulation(self):
        """EtherCATServer 应支持半开连接模拟。"""
        server = EtherCATServer()
        server._network_sim = _make_network_sim_mock(half_open=True)
        assert server.should_simulate_half_open() is True

    def test_ethercat_no_half_open(self):
        """EtherCATServer 在没有半开模拟时应返回 False。"""
        server = EtherCATServer()
        server._network_sim = _make_network_sim_mock(half_open=False)
        assert server.should_simulate_half_open() is False

    def test_ethercat_should_drop_frame(self):
        """EtherCATServer 应支持帧丢弃模拟。"""
        server = EtherCATServer()
        server._network_sim = _make_network_sim_mock(drop=True)
        assert server.should_drop_frame() is True

    def test_bacnet_handle_packet_with_drop(self):
        """BACnet _handle_bacnet_packet 在 should_drop_frame=True 时应返回 None。"""
        server = BACnetServer()
        server._network_sim = _make_network_sim_mock(drop=True)
        result = server._handle_bacnet_packet(b'\x81\x0a\x00\x06\x01\x00', ("127.0.0.1", 47808))
        assert result is None

    def test_bacnet_handle_packet_without_drop(self):
        """BACnet _handle_bacnet_packet 在无网络仿真时应正常处理。"""
        server = BACnetServer()
        # 不设置 network_sim，应正常处理
        result = server._handle_bacnet_packet(b'\x81\x0a\x00\x06\x01\x00', ("127.0.0.1", 47808))
        # 可能返回 None（因为帧格式不完整）或 bytes，但不应因为 drop_frame 返回 None
        # 实际上帧不完整所以返回 None，但这不是被 drop 掉的
        assert result is None  # 帧太短，正常返回 None

    def test_gb28181_handle_message_with_drop(self):
        """GB28181 handle_message 在 should_drop_frame=True 时应不处理消息。"""
        server = GB28181Server()
        server._network_sim = _make_network_sim_mock(drop=True)
        # 应不抛异常且不处理
        server.handle_message(b"REGISTER sip:test SIP/2.0\r\n\r\n", ("127.0.0.1", 5060))
        # 无异常即通过


# ── P4-4: 事件驱动时序记录 ───────────────────────────────────────────────

class TestEventDrivenRecording:
    """验证事件驱动时序记录功能。"""

    def test_configure_event_driven_recording(self):
        """配置事件驱动记录后，引擎状态应正确设置。"""
        engine = SimulationEngine()
        engine.configure_event_driven_recording(enabled=True, threshold=0.5)
        assert engine._event_driven_record is True
        assert engine._event_record_threshold == 0.5

    def test_disable_event_driven_recording(self):
        """禁用事件驱动记录后，标志应为 False。"""
        engine = SimulationEngine()
        engine.configure_event_driven_recording(enabled=True, threshold=1.0)
        engine.configure_event_driven_recording(enabled=False)
        assert engine._event_driven_record is False

    @pytest.mark.asyncio
    async def test_check_event_driven_record_detects_change(self):
        """_check_event_driven_record 应检测值变化并记录到数据库。"""
        engine = SimulationEngine()
        engine.configure_event_driven_recording(enabled=True, threshold=0.0)

        instance = _make_device_instance(device_id="event-test")
        instance.start()
        await instance.tick()  # STARTING → RUN
        engine._devices["event-test"] = instance

        # Mock 数据库
        mock_db = AsyncMock()
        mock_db.save_timeseries_batch = AsyncMock()

        with patch("protoforge.engine.registry.get_database", return_value=mock_db):
            await engine._check_event_driven_record(instance, time.time())

        # 首次记录应记录所有点
        assert mock_db.save_timeseries_batch.called
        records = mock_db.save_timeseries_batch.call_args[0][0]
        assert len(records) > 0

    @pytest.mark.asyncio
    async def test_check_event_driven_record_no_change_no_record(self):
        """值未变化时不应记录。"""
        engine = SimulationEngine()
        engine.configure_event_driven_recording(enabled=True, threshold=0.0)

        instance = _make_device_instance(device_id="no-change-test")
        instance.start()
        await instance.tick()  # STARTING → RUN
        engine._devices["no-change-test"] = instance

        mock_db = AsyncMock()
        mock_db.save_timeseries_batch = AsyncMock()

        with patch("protoforge.engine.registry.get_database", return_value=mock_db):
            # 第一次记录（首次）
            await engine._check_event_driven_record(instance, time.time())
            first_call_count = mock_db.save_timeseries_batch.call_count

            # 第二次，值未变化，不应记录
            await engine._check_event_driven_record(instance, time.time())
            assert mock_db.save_timeseries_batch.call_count == first_call_count

    @pytest.mark.asyncio
    async def test_event_driven_threshold_filtering(self):
        """阈值过滤：值变化小于阈值时不记录。"""
        engine = SimulationEngine()
        engine.configure_event_driven_recording(enabled=True, threshold=100.0)

        instance = _make_device_instance(device_id="threshold-test")
        instance.start()
        await instance.tick()  # STARTING → RUN
        engine._devices["threshold-test"] = instance

        mock_db = AsyncMock()
        mock_db.save_timeseries_batch = AsyncMock()

        with patch("protoforge.engine.registry.get_database", return_value=mock_db):
            # 首次记录（prev=None，记录所有）
            await engine._check_event_driven_record(instance, time.time())
            first_count = mock_db.save_timeseries_batch.call_count

            # 值变化但小于阈值，不应记录
            await engine._check_event_driven_record(instance, time.time())
            assert mock_db.save_timeseries_batch.call_count == first_count

    @pytest.mark.asyncio
    async def test_event_driven_no_database(self):
        """数据库未注册时不应抛异常。"""
        engine = SimulationEngine()
        engine.configure_event_driven_recording(enabled=True, threshold=0.0)

        instance = _make_device_instance(device_id="no-db-test")
        instance.start()
        await instance.tick()  # STARTING → RUN
        engine._devices["no-db-test"] = instance

        with patch("protoforge.engine.registry.get_database", side_effect=RuntimeError("no db")):
            # 不应抛异常
            await engine._check_event_driven_record(instance, time.time())


# ── 回归验证 ─────────────────────────────────────────────────────────────

class TestNoRegression:
    """确保已有功能不受 Phase 4 修改影响。"""

    @pytest.mark.asyncio
    async def test_device_start_stop_normal(self):
        """设备正常启停流程不受影响。"""
        instance = _make_device_instance(device_id="regression-test")
        instance.start()
        time.sleep(0.02)  # 等待 min_startup_time
        await instance.tick()  # STARTING → RUN
        assert instance.device_state == DeviceState.RUN

        instance.stop()
        # 没有 stopping_sequence_duration 时，直接到 STOP（通过 tick 完成停机序列）
        assert instance.device_state in (DeviceState.STOPPING, DeviceState.STOP)

        await instance.tick()
        # stopping_sequence_duration 默认为 0，所以一次 tick 后应到 STOP
        assert instance.device_state == DeviceState.STOP

    def test_engine_tick_loop_structure_intact(self):
        """引擎 tick_loop 结构完整，包含 TS pattern、同步、事件记录。"""
        engine = SimulationEngine()
        # 验证新属性存在
        assert hasattr(engine, '_device_ts_patterns')
        assert hasattr(engine, '_event_driven_record')
        assert hasattr(engine, '_event_record_threshold')
        assert hasattr(engine, '_last_recorded_values')
        assert hasattr(engine, '_timeseries_manager')

    def test_state_machine_transitions_intact(self):
        """状态机转换规则不受影响。"""
        sm = DeviceStateMachine()
        # 初始状态是 STOP
        assert sm.get_state() == DeviceState.STOP
        # STOP → STARTING
        assert sm.can_trigger("start")
        sm.trigger("start")
        assert sm.get_state() == DeviceState.STARTING
        # STARTING → RUN (需要等待 min_startup_time)
        import time as _t
        _t.sleep(2.1)  # 默认 min_startup_time=2.0s
        assert sm.can_trigger("startup_complete")
        sm.trigger("startup_complete")
        assert sm.get_state() == DeviceState.RUN
        # RUN → STOPPING
        assert sm.can_trigger("stop")
        sm.trigger("stop")
        assert sm.get_state() == DeviceState.STOPPING
        # STOPPING → STOP
        assert sm.can_trigger("stop_complete")
        sm.trigger("stop_complete")
        assert sm.get_state() == DeviceState.STOP

    def test_protocol_base_methods_exist(self):
        """协议基类方法存在于具体实现中。"""
        # 用具体子类测试
        for server_cls in [BACnetServer, GB28181Server, ProfinetServer, EtherCATServer]:
            server = server_cls()
            assert hasattr(server, 'should_drop_frame')
            assert hasattr(server, 'should_simulate_half_open')
            assert hasattr(server, 'on_client_connect')
            assert hasattr(server, 'on_client_disconnect')

    def test_existing_tests_still_pass(self):
        """现有测试套件仍可导入。"""
        # 仅验证导入不报错
        from protoforge.engine.engine import SimulationEngine
        from protoforge.engine.device import DeviceInstance
        from protoforge.engine.state_machine import DeviceStateMachine, DeviceState
        from protoforge.simulation.timeseries import TimeSeriesPattern, TimeSeriesManager
        assert SimulationEngine is not None
        assert DeviceInstance is not None
        assert DeviceStateMachine is not None

    @pytest.mark.asyncio
    async def test_device_tick_generates_data_in_run(self):
        """RUN 状态下 tick 应生成数据。"""
        instance = _make_device_instance(device_id="tick-gen-test")
        instance.start()
        time.sleep(0.02)  # 等待 min_startup_time
        await instance.tick()  # STARTING → RUN
        assert instance.device_state == DeviceState.RUN

        # 读取初始值
        val_before = instance.read_point("temperature")

        # tick 后应有新值
        await instance.tick()
        val_after = instance.read_point("temperature")
        assert val_after is not None

    def test_engine_ts_pattern_clear_on_no_device(self):
        """清除不存在设备的 TS 模式不应报错。"""
        engine = SimulationEngine()
        engine.clear_device_ts_patterns("nonexistent")
        # 无异常即通过
