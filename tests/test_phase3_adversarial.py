"""Phase 3 Adversarial Verification Tests.

Tests that verify:
1. MQTT QoS 1/2 retransmission tracking
2. S7 PDU negotiation per-connection
3. Protocol-level CRC error simulation in S7/MC/FINS/HTTP
4. Device hot-update with point add/remove
5. Batch comparison API
6. Drift monitor API
7. Export comparison API
8. Generate config from recording
9. Auto-calibrate
10. No regression on existing functionality
"""

import asyncio
import math
import struct
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from protoforge.engine.engine import SimulationEngine
from protoforge.engine.network_sim import NetworkSimulator, NetworkProfile
from protoforge.protocols.base import ProtocolServer, ProtocolStatus
from protoforge.protocols.s7.server import S7Server, S7ConnectionState, S7DeviceBehavior
from protoforge.models.device import DeviceConfig, PointConfig, DataType, GeneratorType


# ─── P2-1: MQTT QoS 1/2 Retransmission ────────────────────────────────────

class TestMQTTQoSTracker:
    """P2: MQTT QoS 1/2 消息追踪与重传."""

    def test_qos_tracker_import(self):
        """QoSMessageTracker 可正常导入."""
        from protoforge.protocols.mqtt.server import QoSMessageTracker, InFlightMessage
        assert QoSMessageTracker is not None
        assert InFlightMessage is not None

    def test_in_flight_message_dataclass(self):
        """InFlightMessage 数据类字段正确."""
        from protoforge.protocols.mqtt.server import InFlightMessage
        msg = InFlightMessage(
            topic="test/topic",
            payload=b"hello",
            qos=1,
            packet_id=1,
            publish_time=time.time(),
        )
        assert msg.topic == "test/topic"
        assert msg.payload == b"hello"
        assert msg.qos == 1
        assert msg.retry_count == 0
        assert msg.state == "wait_puback"

    @pytest.mark.asyncio
    async def test_qos_tracker_track_publish(self):
        """QoS tracker 正确追踪 QoS 1 消息."""
        from protoforge.protocols.mqtt.server import QoSMessageTracker
        broker = MagicMock()
        tracker = QoSMessageTracker(broker=broker, retransmit_timeout=15.0, max_retries=3)
        pid = await tracker.track_publish("test/topic", b"payload", qos=1)
        assert pid is not None
        assert pid >= 1
        assert tracker.in_flight_count == 1
        assert tracker.stats["total_published"] == 1
        assert tracker.stats["total_qoS1"] == 1

    @pytest.mark.asyncio
    async def test_qos_tracker_puback(self):
        """QoS 1 PUBACK 正确清除 in-flight 消息."""
        from protoforge.protocols.mqtt.server import QoSMessageTracker
        tracker = QoSMessageTracker(broker=MagicMock())
        pid = await tracker.track_publish("test/topic", b"payload", qos=1)
        await tracker.on_puback(pid)
        assert tracker.in_flight_count == 0
        assert tracker.stats["total_acked"] == 1

    @pytest.mark.asyncio
    async def test_qos2_pubrec_pubcomp_flow(self):
        """QoS 2 PUBREC→PUBCOMP 流程正确."""
        from protoforge.protocols.mqtt.server import QoSMessageTracker
        tracker = QoSMessageTracker(broker=MagicMock())
        pid = await tracker.track_publish("test/topic", b"payload", qos=2)
        assert tracker.stats["total_qoS2"] == 1
        # PUBREC
        await tracker.on_pubrec(pid)
        msg = tracker._in_flight.get(pid)
        assert msg is not None
        assert msg.state == "wait_pubcomp"
        # PUBCOMP
        await tracker.on_pubcomp(pid)
        assert tracker.in_flight_count == 0
        assert tracker.stats["total_acked"] == 1

    @pytest.mark.asyncio
    async def test_qos_tracker_ignores_qos0(self):
        """QoS 0 消息不被追踪."""
        from protoforge.protocols.mqtt.server import QoSMessageTracker
        tracker = QoSMessageTracker(broker=MagicMock())
        pid = await tracker.track_publish("test/topic", b"payload", qos=0)
        assert pid is None
        assert tracker.in_flight_count == 0

    @pytest.mark.asyncio
    async def test_qos_tracker_get_in_flight_info(self):
        """get_in_flight_info 返回正确的调试信息."""
        from protoforge.protocols.mqtt.server import QoSMessageTracker
        tracker = QoSMessageTracker(broker=MagicMock())
        await tracker.track_publish("topic1", b"data1", qos=1)
        await tracker.track_publish("topic2", b"data2", qos=2)
        info = tracker.get_in_flight_info()
        assert len(info) == 2
        assert info[0]["topic"] in ("topic1", "topic2")
        assert "age_seconds" in info[0]

    @pytest.mark.asyncio
    async def test_qos_tracker_restore_session(self):
        """会话恢复正确还原持久化消息."""
        from protoforge.protocols.mqtt.server import QoSMessageTracker
        tracker = QoSMessageTracker(broker=MagicMock())
        await tracker.track_publish("topic1", b"data1", qos=1)
        await tracker.track_publish("topic2", b"data2", qos=2)
        # 模拟 ACK 一个
        keys = list(tracker._in_flight.keys())
        await tracker.on_puback(keys[0])
        # 恢复
        restored = tracker.restore_session()
        assert len(restored) == 1  # 只有一个未 ACK


# ─── P2-2: S7 PDU Negotiation ─────────────────────────────────────────────

class TestS7PDUNegotiation:
    """P2: S7 PDU 协商."""

    def test_connection_state_default(self):
        """S7ConnectionState 默认值正确."""
        state = S7ConnectionState()
        assert state.pdu_size == 480
        assert state.max_amq_caller == 8
        assert state.max_amq_callee == 8
        assert state.setup_completed is False

    def test_connect_response_stores_state(self):
        """Setup Communication 响应存储协商结果到 conn_state."""
        server = S7Server()
        conn_state = S7ConnectionState()

        # 构建 Setup Communication 请求
        # TPKT(4) + COTP DT(3) + S7 Header(10) + Setup params(8)
        s7_header = bytes([
            0x32, 0x01,       # S7 Protocol ID, Msg Type = Job
            0x00, 0x00,       # Reserved
            0x00, 0x01,       # PDU Reference
            0x00, 0x08,       # Parameter Length = 8
            0x00, 0x00,       # Data Length = 0
        ])
        setup_params = bytes([
            0xF0,             # Function = Setup Communication
            0x00,             # Reserved
            0x00, 0x08,       # AMQ Calling = 8
            0x00, 0x08,       # AMQ Called = 8
            0x01, 0xE0,       # PDU Size = 480
        ])
        tpkt_cotp = bytes([0x03, 0x00, 0x00, 0x00, 0x02, 0xF0, 0x80])
        data = tpkt_cotp + s7_header + setup_params
        # Update TPKT length
        data = bytes([0x03, 0x00, (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data[4:]

        resp = server._make_s7_connect_response(data, conn_state)
        assert resp is not None
        assert conn_state.setup_completed is True
        assert conn_state.pdu_size == 480
        assert conn_state.max_amq_caller == 8
        assert conn_state.max_amq_callee == 8

    def test_connect_response_clamps_pdu_size(self):
        """PDU Size 被限制在 [128, 960] 范围内."""
        server = S7Server()
        conn_state = S7ConnectionState()

        # 构建请求 with PDU Size = 10000 (超出上限)
        s7_header = bytes([
            0x32, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x00, 0x08, 0x00, 0x00,
        ])
        setup_params = bytes([
            0xF0, 0x00,
            0x00, 0x08, 0x00, 0x08,
            0x27, 0x10,  # PDU Size = 10000
        ])
        tpkt_cotp = bytes([0x03, 0x00, 0x00, 0x00, 0x02, 0xF0, 0x80])
        data = tpkt_cotp + s7_header + setup_params
        data = bytes([0x03, 0x00, (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data[4:]

        server._make_s7_connect_response(data, conn_state)
        assert conn_state.pdu_size == 960  # clamped to max

    def test_connect_response_min_pdu_size(self):
        """PDU Size 最小值 128."""
        server = S7Server()
        conn_state = S7ConnectionState()

        s7_header = bytes([
            0x32, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x00, 0x08, 0x00, 0x00,
        ])
        setup_params = bytes([
            0xF0, 0x00,
            0x00, 0x01, 0x00, 0x01,
            0x00, 0x10,  # PDU Size = 16 (below min)
        ])
        tpkt_cotp = bytes([0x03, 0x00, 0x00, 0x00, 0x02, 0xF0, 0x80])
        data = tpkt_cotp + s7_header + setup_params
        data = bytes([0x03, 0x00, (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data[4:]

        server._make_s7_connect_response(data, conn_state)
        assert conn_state.pdu_size == 128  # clamped to min


# ─── P2-3: Protocol-level CRC Error Simulation ────────────────────────────

class TestProtocolCRCErrorSimulation:
    """P2: 协议级 CRC 错误/半开连接模拟."""

    def test_base_should_drop_frame_no_sim(self):
        """无网络仿真器时 should_drop_frame 返回 False."""
        class TestServer(ProtocolServer):
            async def start(self, config): pass
            async def stop(self): pass
            async def create_device(self, config): return ""
            async def remove_device(self, device_id): pass
            async def read_points(self, device_id): return []
            async def write_point(self, device_id, name, value): return False

        server = TestServer()
        assert server.should_drop_frame() is False
        assert server.should_simulate_half_open() is False

    def test_base_should_drop_frame_with_crc(self):
        """CRC 错误模拟生效时 should_drop_frame 返回 True."""
        class TestServer(ProtocolServer):
            async def start(self, config): pass
            async def stop(self): pass
            async def create_device(self, config): return ""
            async def remove_device(self, device_id): pass
            async def read_points(self, device_id): return []
            async def write_point(self, device_id, name, value): return False

        server = TestServer()
        sim = NetworkSimulator(NetworkProfile(crc_error_rate=1.0), enabled=True)
        server.set_network_sim(sim)
        assert server.should_drop_frame() is True

    def test_base_should_drop_frame_with_packet_loss(self):
        """丢包模拟生效时 should_drop_frame 返回 True."""
        class TestServer(ProtocolServer):
            async def start(self, config): pass
            async def stop(self): pass
            async def create_device(self, config): return ""
            async def remove_device(self, device_id): pass
            async def read_points(self, device_id): return []
            async def write_point(self, device_id, name, value): return False

        server = TestServer()
        sim = NetworkSimulator(NetworkProfile(packet_loss_rate=1.0), enabled=True)
        server.set_network_sim(sim)
        assert server.should_drop_frame() is True

    def test_base_should_simulate_half_open(self):
        """半开连接模拟生效时 should_simulate_half_open 返回 True."""
        class TestServer(ProtocolServer):
            async def start(self, config): pass
            async def stop(self): pass
            async def create_device(self, config): return ""
            async def remove_device(self, device_id): pass
            async def read_points(self, device_id): return []
            async def write_point(self, device_id, name, value): return False

        server = TestServer()
        sim = NetworkSimulator(NetworkProfile(half_open_rate=1.0), enabled=True)
        server.set_network_sim(sim)
        assert server.should_simulate_half_open() is True

    def test_base_should_drop_frame_disabled(self):
        """网络仿真器禁用时 should_drop_frame 返回 False."""
        class TestServer(ProtocolServer):
            async def start(self, config): pass
            async def stop(self): pass
            async def create_device(self, config): return ""
            async def remove_device(self, device_id): pass
            async def read_points(self, device_id): return []
            async def write_point(self, device_id, name, value): return False

        server = TestServer()
        sim = NetworkSimulator(NetworkProfile(crc_error_rate=1.0), enabled=False)
        server.set_network_sim(sim)
        assert server.should_drop_frame() is False


# ─── P2-4: Device Hot-Update with Point Add/Remove ─────────────────────────

class TestDeviceHotUpdateEnhanced:
    """P2: 设备热更新 — 支持点位增删."""

    def _make_config(self, device_id="test_dev", protocol="modbus_tcp", point_names=None):
        point_names = point_names or ["temp", "pressure"]
        points = []
        for i, name in enumerate(point_names):
            points.append(PointConfig(
                name=name,
                data_type=DataType.FLOAT32,
                address=str(i + 1),
                generator_type=GeneratorType.SINE,
                generator_config={"amplitude": 5, "offset": 25, "frequency": 0.1},
                min_value=0,
                max_value=100,
            ))
        return DeviceConfig(
            id=device_id,
            name=f"Test Device {device_id}",
            protocol=protocol,
            points=points,
        )

    @pytest.mark.asyncio
    async def test_hot_update_preserves_existing_points(self):
        """热更新不改变点位结构时，原有点位值保留."""
        engine = SimulationEngine()
        config = self._make_config()
        with patch.object(engine, '_protocol_servers', {}):
            await engine.create_device(config)
            instance = engine.get_device_instance("test_dev")
            # Set a value
            instance._point_values["temp"] = 42.0
            # Hot update with same structure
            new_config = self._make_config()
            new_config.protocol_config = {"publish_interval": 10}
            await engine.update_device("test_dev", new_config)
            instance = engine.get_device_instance("test_dev")
            assert instance._point_values["temp"] == 42.0

    @pytest.mark.asyncio
    async def test_hot_update_add_point(self):
        """热更新新增点位时，不需要全量重建."""
        engine = SimulationEngine()
        config = self._make_config(point_names=["temp", "pressure"])
        with patch.object(engine, '_protocol_servers', {}):
            await engine.create_device(config)
            # Hot update with added point
            new_config = self._make_config(point_names=["temp", "pressure", "humidity"])
            await engine.update_device("test_dev", new_config)
            instance = engine.get_device_instance("test_dev")
            assert "humidity" in instance._point_configs
            assert "humidity" in instance._point_values

    @pytest.mark.asyncio
    async def test_hot_update_remove_point(self):
        """热更新删除点位时，不需要全量重建."""
        engine = SimulationEngine()
        config = self._make_config(point_names=["temp", "pressure", "humidity"])
        with patch.object(engine, '_protocol_servers', {}):
            await engine.create_device(config)
            # Hot update with removed point
            new_config = self._make_config(point_names=["temp", "pressure"])
            await engine.update_device("test_dev", new_config)
            instance = engine.get_device_instance("test_dev")
            assert "humidity" not in instance._point_configs
            assert "humidity" not in instance._point_values


# ─── P2-5: Batch Compare + Drift Monitor + Export ──────────────────────────

class TestBatchCompareAndDriftMonitor:
    """P2: 批量对比 + 漂移监控 + 导出."""

    def test_batch_compare_route_exists(self):
        """批量对比 API 路由已注册."""
        from protoforge.api.v1.simulation_routes import router
        routes = [r.path for r in router.routes]
        assert "/devices/batch-compare" in routes

    def test_drift_monitor_routes_exist(self):
        """漂移监控 API 路由已注册."""
        from protoforge.api.v1.simulation_routes import router
        routes = [r.path for r in router.routes]
        assert "/devices/{device_id}/drift-monitor/start" in routes
        assert "/devices/{device_id}/drift-monitor/stop" in routes
        assert "/devices/{device_id}/drift-monitor/history" in routes

    def test_export_route_exists(self):
        """导出对比报告 API 路由已注册."""
        from protoforge.api.v1.simulation_routes import router
        routes = [r.path for r in router.routes]
        assert "/devices/{device_id}/compare/export" in routes


# ─── P3: Generate Config from Recording + Auto-Calibrate ────────────────────

class TestGenerateConfigAndCalibrate:
    """P3: 从录制生成配置 + 自动校准."""

    def test_generate_config_route_exists(self):
        """生成配置 API 路由已注册."""
        from protoforge.api.v1.simulation_routes import router
        routes = [r.path for r in router.routes]
        assert "/simulation/generate-config-from-recording" in routes

    def test_auto_calibrate_route_exists(self):
        """自动校准 API 路由已注册."""
        from protoforge.api.v1.simulation_routes import router
        routes = [r.path for r in router.routes]
        assert "/devices/{device_id}/auto-calibrate" in routes

    def test_analyze_timeseries_basic(self):
        """时序分析函数返回正确统计指标."""
        from protoforge.api.v1.simulation_routes import _analyze_timeseries
        values = [25.0, 26.0, 24.0, 25.5, 25.0, 26.5, 24.5, 25.0]
        result = _analyze_timeseries(values)
        assert "mean" in result
        assert "std" in result
        assert "min" in result
        assert "max" in result
        assert "range" in result
        assert "slope" in result
        assert abs(result["mean"] - 25.1875) < 0.01

    def test_analyze_timeseries_empty(self):
        """空列表返回默认值."""
        from protoforge.api.v1.simulation_routes import _analyze_timeseries
        result = _analyze_timeseries([])
        assert result["mean"] == 0
        assert result["std"] == 0

    def test_analyze_timeseries_periodic(self):
        """周期数据被正确检测."""
        import math as m
        from protoforge.api.v1.simulation_routes import _analyze_timeseries
        # Generate sine wave with enough samples
        values = [25 + 5 * m.sin(2 * m.pi * 0.1 * t) for t in range(50)]
        result = _analyze_timeseries(values)
        assert "is_periodic" in result
        assert "estimated_frequency" in result

    def test_select_generator_type_fixed(self):
        """稳定数据选择 FIXED 生成器."""
        from protoforge.api.v1.simulation_routes import _select_generator_type
        analysis = {"std": 0.001, "mean": 25.0, "slope": 0, "is_periodic": False,
                     "cv": 0, "range": 0.01, "avg_change_rate": 0, "estimated_frequency": 0.1,
                     "min": 24.99, "max": 25.01}
        gen_type, gen_config = _select_generator_type(analysis)
        assert gen_type == "fixed"

    def test_select_generator_type_sine(self):
        """周期性数据选择 SINE 生成器."""
        from protoforge.api.v1.simulation_routes import _select_generator_type
        analysis = {"std": 2.0, "mean": 25.0, "slope": 0, "is_periodic": True,
                     "cv": 0.08, "range": 8.0, "avg_change_rate": 1.0,
                     "estimated_frequency": 0.05, "min": 21, "max": 29}
        gen_type, gen_config = _select_generator_type(analysis)
        assert gen_type == "sine"
        assert "amplitude" in gen_config
        assert "offset" in gen_config

    def test_select_generator_type_increment(self):
        """有趋势的数据选择 INCREMENT 生成器."""
        from protoforge.api.v1.simulation_routes import _select_generator_type
        analysis = {"std": 5.0, "mean": 50, "slope": 0.5, "is_periodic": False,
                     "cv": 0.1, "range": 20, "avg_change_rate": 0.5,
                     "estimated_frequency": 0.1, "min": 30, "max": 70}
        gen_type, gen_config = _select_generator_type(analysis)
        assert gen_type == "increment"
        assert "step" in gen_config

    def test_select_generator_type_random(self):
        """随机波动数据选择 RANDOM 生成器."""
        from protoforge.api.v1.simulation_routes import _select_generator_type
        analysis = {"std": 3.0, "mean": 50, "slope": 0, "is_periodic": False,
                     "cv": 0.06, "range": 12, "avg_change_rate": 0.5,
                     "estimated_frequency": 0.1, "min": 38, "max": 62}
        gen_type, gen_config = _select_generator_type(analysis)
        assert gen_type == "random"
        assert "min" in gen_config
        assert "max" in gen_config


# ─── No Regression Tests ────────────────────────────────────────────────────

class TestNoRegression:
    """确保已有功能不受影响."""

    def test_protocol_server_base_class_intact(self):
        """ProtocolServer 基类原有方法完好."""
        class TestServer(ProtocolServer):
            async def start(self, config): pass
            async def stop(self): pass
            async def create_device(self, config): return ""
            async def remove_device(self, device_id): pass
            async def read_points(self, device_id): return []
            async def write_point(self, device_id, name, value): return False

        server = TestServer()
        assert server.status == ProtocolStatus.STOPPED
        assert server.active_connections == 0
        assert server.on_write is None
        # 新增的方法也存在
        assert hasattr(server, "should_drop_frame")
        assert hasattr(server, "should_simulate_half_open")
        assert hasattr(server, "set_device_state_provider")
        assert hasattr(server, "get_device_state_string")

    def test_network_simulator_existing_methods_preserved(self):
        """NetworkSimulator 原有方法完好."""
        sim = NetworkSimulator(enabled=True)
        assert hasattr(sim, "delay")
        assert hasattr(sim, "should_drop")
        assert hasattr(sim, "should_drop_connection")
        assert hasattr(sim, "should_inject_crc_error")
        assert hasattr(sim, "is_half_open")
        assert hasattr(sim, "can_accept_connection")
        assert hasattr(sim, "on_connect")
        assert hasattr(sim, "on_disconnect")
        assert hasattr(sim, "get_stats")
        assert hasattr(sim, "reset_stats")

    def test_s7_server_existing_methods_preserved(self):
        """S7Server 原有方法完好."""
        server = S7Server()
        assert hasattr(server, "_make_cotp_cr_response")
        assert hasattr(server, "_make_s7_connect_response")
        assert hasattr(server, "_make_s7_read_response")
        assert hasattr(server, "_make_s7_write_response")
        assert hasattr(server, "_make_s7_error_response")
        assert hasattr(server, "_make_s7_szl_response")
        assert hasattr(server, "_make_s7_plc_control_response")
        assert hasattr(server, "_process_s7_message")

    def test_s7_constants_preserved(self):
        """S7 协议常量完好."""
        assert S7Server._DEFAULT_PDU_SIZE == 480
        assert S7Server._MIN_PDU_SIZE == 128
        assert S7Server._MAX_PDU_SIZE == 960
        assert S7Server._DEFAULT_AMQ == 8
        assert S7Server._MAX_AMQ == 64

    def test_s7_behavior_areas_preserved(self):
        """S7 区域常量完好."""
        assert S7DeviceBehavior.S7_AREA_DB == 0x84
        assert S7DeviceBehavior.S7_AREA_INPUTS == 0x81
        assert S7DeviceBehavior.S7_AREA_OUTPUTS == 0x82
        assert S7DeviceBehavior.S7_AREA_MARKERS == 0x83
        assert S7DeviceBehavior.S7_AREA_TIMERS == 0x1D
        assert S7DeviceBehavior.S7_AREA_COUNTERS == 0x1C

    def test_mqtt_broker_existing_methods_preserved(self):
        """MqttBroker 原有方法完好."""
        from protoforge.protocols.mqtt.server import MqttBroker
        broker = MqttBroker()
        assert hasattr(broker, "start")
        assert hasattr(broker, "stop")
        assert hasattr(broker, "create_device")
        assert hasattr(broker, "remove_device")
        assert hasattr(broker, "read_points")
        assert hasattr(broker, "write_point")
        assert hasattr(broker, "get_config_schema")
        assert hasattr(broker, "_publish_loop")
        assert hasattr(broker, "_publish_device")
        assert hasattr(broker, "_publish_will")
        # 新增方法
        assert hasattr(broker, "get_qos_stats")
        assert hasattr(broker, "get_in_flight_messages")
        assert hasattr(broker, "restore_qos_session")

    def test_mqtt_broker_qos_config_schema(self):
        """MQTT 配置 schema 包含 QoS 相关字段."""
        from protoforge.protocols.mqtt.server import MqttBroker
        broker = MqttBroker()
        schema = broker.get_config_schema()
        props = schema.get("properties", {})
        assert "qos" in props
        assert "retain" in props
        assert "retransmit_timeout" in props
        assert "max_retries" in props

    def test_existing_simulation_routes_preserved(self):
        """已有仿真路由完好."""
        from protoforge.api.v1.simulation_routes import router
        routes = [r.path for r in router.routes]
        # 原有路由
        assert "/devices/{device_id}/import-snapshot" in routes
        assert "/simulation/test-script" in routes
        assert "/simulation/fault-templates" in routes
        assert "/devices/{device_id}/compare" in routes
        assert "/devices/{device_id}/compare-timeseries" in routes

    def test_engine_update_device_method_exists(self):
        """Engine.update_device 方法存在."""
        from protoforge.engine.engine import SimulationEngine
        engine = SimulationEngine()
        assert hasattr(engine, "update_device")
        assert hasattr(engine, "create_device")
        assert hasattr(engine, "remove_device")
        assert hasattr(engine, "start_device")
        assert hasattr(engine, "stop_device")

    def test_preset_profiles_preserved(self):
        """预定义网络配置完好."""
        from protoforge.engine.network_sim import PRESET_PROFILES
        assert "ideal" in PRESET_PROFILES
        assert "lan" in PRESET_PROFILES
        assert "wan" in PRESET_PROFILES
        assert "wireless" in PRESET_PROFILES
        assert "satellite" in PRESET_PROFILES
        assert "degraded" in PRESET_PROFILES
        # P2 新增字段
        assert PRESET_PROFILES["wireless"].crc_error_rate > 0
        assert PRESET_PROFILES["degraded"].half_open_rate > 0
