"""Phase 2 Adversarial Verification Tests.

Tests that verify:
1. Modbus Exception Codes for non-RUN device states
2. Device state auto-restore on engine start
3. Protocol-level CRC error / half-open connection simulation
4. Device parameter hot-update
5. Simulation vs real device comparison API
6. Script tester API
7. OPC-UA HistoricalAccess
8. No regression on existing functionality
"""

import struct
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from protoforge.engine.engine import SimulationEngine
from protoforge.engine.network_sim import PRESET_PROFILES, NetworkProfile, NetworkSimulator
from protoforge.engine.state_machine import DeviceState, DeviceStateMachine
from protoforge.models.device import DataType, DeviceConfig, PointConfig
from protoforge.protocols.base import ProtocolServer, ProtocolStatus
from protoforge.protocols.modbus.server import ModbusTcpServer

# ─── Fix 1: Modbus Exception Codes ─────────────────────────────────────────

class TestModbusExceptionCodes:
    """P1: Modbus 异常码 — 设备非 RUN 状态时返回 Modbus Exception Code."""

    def test_exception_response_format(self):
        """异常响应帧格式正确：FC|0x80, ExceptionCode."""
        server = ModbusTcpServer()
        resp = server._err_response(0x03, 0x04)
        assert resp == bytes([0x83, 0x04])
        assert resp[0] & 0x80  # 高位置1表示异常
        assert resp[1] == 0x04  # Slave Device Failure

    def test_exception_codes_defined(self):
        """所有必要的异常码已定义."""
        server = ModbusTcpServer()
        assert server._EX_SLAVE_DEVICE_FAILURE == 0x04
        assert server._EX_ACKNOWLEDGE == 0x05
        assert server._EX_SLAVE_DEVICE_BUSY == 0x06
        assert server._EX_GATEWAY_PATH_UNAVAILABLE == 0x0A

    def test_state_exception_mapping(self):
        """设备状态→Modbus异常码映射正确（stop/starting/stopping 不拦截请求，见设计注释）."""
        server = ModbusTcpServer()
        assert server._STATE_EXCEPTION_CODES["error"] == 0x04
        assert server._STATE_EXCEPTION_CODES["maintenance"] == 0x06
        assert server._STATE_EXCEPTION_CODES["program"] == 0x0A
        # FIXED-P1: starting/stopping 过渡期照常应答（返回最后已知值），与真实设备行为一致；
        # 原先映射 0x05 导致设备自动拉起后 STARTING 窗口期内轮询全部收到异常响应
        assert "starting" not in server._STATE_EXCEPTION_CODES
        assert "stopping" not in server._STATE_EXCEPTION_CODES
        assert "stop" not in server._STATE_EXCEPTION_CODES  # 停机设备仍响应读请求（返回最后已知值）

    def test_device_state_provider_returns_run_by_default(self):
        """无状态提供者时默认返回 run（不阻止正常请求）."""
        server = ModbusTcpServer()
        assert server.get_device_state_string("nonexistent") == "run"

    def test_check_device_state_no_exception_when_run(self):
        """设备在 RUN 状态时不返回异常码."""
        server = ModbusTcpServer()
        # 设置状态提供者返回 run
        server.set_device_state_provider(lambda device_id: "run")
        # 注册一个从站
        server._slave_map["dev1"] = 1
        result = server._check_device_state_for_exception(1)
        assert result is None  # 不返回异常码

    def test_check_device_state_returns_exception_for_error(self):
        """设备在 ERROR 状态时返回 0x04 异常码."""
        server = ModbusTcpServer()
        server.set_device_state_provider(lambda device_id: "error")
        server._slave_map["dev1"] = 1
        result = server._check_device_state_for_exception(1)
        assert result == 0x04  # Slave Device Failure

    def test_check_device_state_returns_no_exception_for_stop(self):
        """设备在 STOP 状态时不返回异常码（停机设备通信模块仍响应，返回最后已知值）."""
        server = ModbusTcpServer()
        server.set_device_state_provider(lambda device_id: "stop")
        server._slave_map["dev1"] = 1
        result = server._check_device_state_for_exception(1)
        assert result is None

    def test_process_frame_returns_exception_for_non_run(self):
        """_process_modbus_frame 在设备非 RUN 时返回异常响应."""
        server = ModbusTcpServer()
        server.set_device_state_provider(lambda device_id: "error")
        server._slave_map["dev1"] = 1
        # 构造一个读保持寄存器请求 (FC03)
        data = struct.pack(">HH", 0, 1)  # start=0, count=1
        resp = server._process_modbus_frame(1, 0x03, data)
        assert resp is not None
        assert resp[0] == 0x83  # FC03 | 0x80
        assert resp[1] == 0x04  # Slave Device Failure

    def test_process_frame_normal_when_run(self):
        """设备在 RUN 状态时正常处理请求."""
        server = ModbusTcpServer()
        server.set_device_state_provider(lambda device_id: "run")
        server._slave_map["dev1"] = 1
        server._get_data_store(1)  # 初始化 data store
        # 构造一个读保持寄存器请求 (FC03)
        data = struct.pack(">HH", 0, 1)
        resp = server._process_modbus_frame(1, 0x03, data)
        assert resp is not None
        assert resp[0] == 0x03  # 正常响应，不是异常


# ─── Fix 2: Device State Auto-Restore ─────────────────────────────────────────

class TestDeviceStateRestore:
    """P2: 设备重启状态自动恢复."""

    @pytest.mark.asyncio
    async def test_restore_calls_import_snapshot(self):
        """引擎启动后调用 _restore_device_states."""
        engine = SimulationEngine()
        # Mock database
        mock_db = AsyncMock()
        mock_db.load_device_snapshots = AsyncMock(return_value=[
            {"point_values": {"temp": 25.0}, "timestamp": time.time(), "id": "snap1"}
        ])
        # Mock import_device_snapshot
        engine.import_device_snapshot = AsyncMock(return_value=True)

        # 添加一个设备
        config = DeviceConfig(id="dev1", name="Test", protocol="modbus_tcp", points=[])
        from protoforge.engine.device import DeviceInstance
        from protoforge.engine.generator import DataGenerator
        instance = DeviceInstance(config, DataGenerator())
        engine._devices["dev1"] = instance

        with patch("protoforge.engine.registry.get_database", return_value=mock_db):
            await engine._restore_device_states()

        engine.import_device_snapshot.assert_called_once()
        call_args = engine.import_device_snapshot.call_args
        assert call_args[0][0] == "dev1"
        assert call_args[0][1]["point_values"]["temp"] == 25.0

    @pytest.mark.asyncio
    async def test_restore_skips_when_no_db(self):
        """数据库不可用时跳过恢复."""
        engine = SimulationEngine()
        with patch("protoforge.engine.registry.get_database", side_effect=RuntimeError("no db")):
            await engine._restore_device_states()
        # 无异常即为通过


# ─── Fix 3: Protocol-Level CRC/Half-Open ──────────────────────────────────────

class TestNetworkSimEnhanced:
    """P2: 协议级通信错误模拟增强."""

    def test_crc_error_rate_field_exists(self):
        """NetworkProfile 包含 crc_error_rate 字段."""
        profile = NetworkProfile(crc_error_rate=0.01)
        assert profile.crc_error_rate == 0.01

    def test_half_open_rate_field_exists(self):
        """NetworkProfile 包含 half_open_rate 字段."""
        profile = NetworkProfile(half_open_rate=0.02)
        assert profile.half_open_rate == 0.02

    def test_should_inject_crc_error_disabled(self):
        """禁用时返回 False."""
        sim = NetworkSimulator(enabled=False)
        assert sim.should_inject_crc_error() is False

    def test_should_inject_crc_error_zero_rate(self):
        """crc_error_rate=0 时返回 False."""
        sim = NetworkSimulator(enabled=True)
        sim._profile = NetworkProfile(crc_error_rate=0.0)
        assert sim.should_inject_crc_error() is False

    def test_should_inject_crc_error_high_rate(self):
        """crc_error_rate=1.0 时必定返回 True."""
        sim = NetworkSimulator(enabled=True)
        sim._profile = NetworkProfile(crc_error_rate=1.0)
        assert sim.should_inject_crc_error() is True
        assert sim._stats["crc_errors"] == 1

    def test_is_half_open_disabled(self):
        """禁用时返回 False."""
        sim = NetworkSimulator(enabled=False)
        assert sim.is_half_open() is False

    def test_is_half_open_high_rate(self):
        """half_open_rate=1.0 时必定返回 True."""
        sim = NetworkSimulator(enabled=True)
        sim._profile = NetworkProfile(half_open_rate=1.0)
        assert sim.is_half_open() is True
        assert sim._stats["half_open_connections"] == 1

    def test_preset_profiles_include_crc_error_rate(self):
        """预定义配置包含 crc_error_rate."""
        degraded = PRESET_PROFILES["degraded"]
        assert degraded.crc_error_rate > 0
        assert degraded.half_open_rate > 0

    def test_profile_to_dict_includes_new_fields(self):
        """to_dict 包含新增字段."""
        profile = NetworkProfile(crc_error_rate=0.01, half_open_rate=0.02)
        d = profile.to_dict()
        assert "crc_error_rate" in d
        assert "half_open_rate" in d

    def test_profile_from_dict_includes_new_fields(self):
        """from_dict 正确解析新增字段."""
        profile = NetworkProfile.from_dict({"crc_error_rate": 0.005, "half_open_rate": 0.01})
        assert profile.crc_error_rate == 0.005
        assert profile.half_open_rate == 0.01

    def test_reset_stats_includes_new_counters(self):
        """reset_stats 包含新统计计数器."""
        sim = NetworkSimulator(enabled=True)
        sim._stats["crc_errors"] = 10
        sim.reset_stats()
        assert sim._stats["crc_errors"] == 0
        assert sim._stats["half_open_connections"] == 0


# ─── Fix 4: Device Hot-Update ────────────────────────────────────────────────

class TestDeviceHotUpdate:
    """P2: 设备参数热更新."""

    @pytest.mark.asyncio
    async def test_hot_update_preserves_device_instance(self):
        """仅 protocol_config 变更时不重建设备实例."""
        engine = SimulationEngine()
        points = [
            PointConfig(name="temp", address="HR0", data_type=DataType.FLOAT32, access="rw")
        ]
        old_config = DeviceConfig(
            id="dev1", name="Test", protocol="modbus_tcp",
            points=points, protocol_config={"scan_cycle_ms": 100}
        )
        from protoforge.engine.device import DeviceInstance
        from protoforge.engine.generator import DataGenerator
        instance = DeviceInstance(old_config, DataGenerator())
        engine._devices["dev1"] = instance

        # 仅修改 protocol_config
        new_config = DeviceConfig(
            id="dev1", name="Test", protocol="modbus_tcp",
            points=points, protocol_config={"scan_cycle_ms": 200}
        )

        await engine.update_device("dev1", new_config)
        # 设备实例应该被保留（同一对象引用）
        assert engine._devices["dev1"] is instance
        assert engine._devices["dev1"].config.protocol_config["scan_cycle_ms"] == 200

    @pytest.mark.asyncio
    async def test_point_hot_update_when_points_change(self):
        """同协议下点位增删走热更新（不重建设备实例）."""
        engine = SimulationEngine()
        old_points = [
            PointConfig(name="temp", address="HR0", data_type=DataType.FLOAT32, access="rw")
        ]
        old_config = DeviceConfig(
            id="dev2", name="Test", protocol="modbus_tcp",
            points=old_points, protocol_config={}
        )
        from protoforge.engine.device import DeviceInstance
        from protoforge.engine.generator import DataGenerator
        instance = DeviceInstance(old_config, DataGenerator())
        engine._devices["dev2"] = instance

        # 添加一个新点位（结构变更）
        new_points = old_points + [
            PointConfig(name="pressure", address="HR2", data_type=DataType.FLOAT32, access="rw")
        ]
        new_config = DeviceConfig(
            id="dev2", name="Test", protocol="modbus_tcp",
            points=new_points, protocol_config={}
        )

        await engine.update_device("dev2", new_config)
        # 同协议下点位增删走热更新，设备实例保留
        assert engine._devices["dev2"] is instance
        # 新点位已被添加
        assert "pressure" in instance._point_configs
        assert "pressure" in instance._point_values
        # 原有点位仍然存在
        assert "temp" in instance._point_configs
        assert "temp" in instance._point_values

    @pytest.mark.asyncio
    async def test_full_rebuild_when_protocol_changes(self):
        """协议变更时走全量重建."""
        engine = SimulationEngine()
        old_points = [
            PointConfig(name="temp", address="HR0", data_type=DataType.FLOAT32, access="rw")
        ]
        old_config = DeviceConfig(
            id="dev3", name="Test", protocol="modbus_tcp",
            points=old_points, protocol_config={}
        )
        from protoforge.engine.device import DeviceInstance
        from protoforge.engine.generator import DataGenerator
        instance = DeviceInstance(old_config, DataGenerator())
        engine._devices["dev3"] = instance

        # 协议变更 → 全量重建
        new_config = DeviceConfig(
            id="dev3", name="Test", protocol="opcua",
            points=old_points, protocol_config={}
        )

        await engine.update_device("dev3", new_config)
        # 设备应该被重建（不同实例）
        assert engine._devices["dev3"] is not instance


# ─── Fix 5: Compare API ──────────────────────────────────────────────────────

class TestCompareAPI:
    """P2: 仿真 vs 真实设备自动对比 API."""

    def test_compare_routes_imported(self):
        """compare 路由可正常导入."""
        from protoforge.api.v1.simulation_routes import (
            compare_device_with_snapshot,
            compare_device_with_timeseries,
        )
        assert callable(compare_device_with_snapshot)
        assert callable(compare_device_with_timeseries)


# ─── Fix 6: Script Tester API ────────────────────────────────────────────────

class TestScriptTester:
    """P2: 脚本编辑器 API."""

    def test_test_script_route_exists(self):
        """test-script 路由可正常导入."""
        from protoforge.api.v1.simulation_routes import test_generator_script
        assert callable(test_generator_script)


# ─── Fix 7: OPC-UA HistoricalAccess ──────────────────────────────────────────

class TestOpcUaHistoricalAccess:
    """P2: OPC-UA HistoricalAccess 基础支持."""

    def test_read_point_history_method_exists(self):
        """OpcUaServer 有 read_point_history 方法."""
        from protoforge.protocols.opcua.server import OpcUaServer
        server = OpcUaServer()
        assert hasattr(server, "read_point_history")
        assert callable(server.read_point_history)

    @pytest.mark.asyncio
    async def test_read_point_history_returns_empty_when_no_db(self):
        """无数据库时返回空列表."""
        from protoforge.protocols.opcua.server import OpcUaServer
        server = OpcUaServer()
        with patch("protoforge.engine.registry.get_database", side_effect=RuntimeError("no db")):
            result = await server.read_point_history("dev1", "temp")
        assert result == []


# ─── No Regression Tests ─────────────────────────────────────────────────────

class TestNoRegression:
    """确保已满足的部分不被破坏."""

    def test_base_protocol_server_has_device_state_provider(self):
        """ProtocolServer 基类有 set_device_state_provider 方法."""
        assert hasattr(ProtocolServer, "set_device_state_provider")
        assert hasattr(ProtocolServer, "get_device_state_string")

    def test_engine_registers_device_state_provider(self):
        """引擎注册协议时设置设备状态提供者."""
        engine = SimulationEngine()
        # 创建一个模拟协议服务器
        mock_server = MagicMock(spec=ProtocolServer)
        mock_server.protocol_name = "test_proto"
        mock_server.status = ProtocolStatus.STOPPED
        engine.register_protocol(mock_server)
        mock_server.set_device_state_provider.assert_called_once()

    def test_engine_get_device_state_for_protocol(self):
        """引擎的设备状态查询回调工作正常."""
        engine = SimulationEngine()
        # 设备不存在时返回 run
        assert engine._get_device_state_for_protocol("nonexistent") == "run"

        # 添加设备后返回实际状态
        config = DeviceConfig(id="dev1", name="Test", protocol="modbus_tcp", points=[])
        from protoforge.engine.device import DeviceInstance
        from protoforge.engine.generator import DataGenerator
        instance = DeviceInstance(config, DataGenerator())
        engine._devices["dev1"] = instance
        # 新设备默认 STOP 状态
        assert engine._get_device_state_for_protocol("dev1") == "stop"

    def test_modbus_existing_functionality_preserved(self):
        """Modbus 原有功能不受影响（非法功能码仍然返回异常码）."""
        server = ModbusTcpServer()
        server.set_device_state_provider(lambda device_id: "run")
        server._slave_map["dev1"] = 1
        server._get_data_store(1)
        # 未知功能码 0x99
        resp = server._process_modbus_frame(1, 0x99, b"")
        assert resp is not None
        assert resp[0] == 0x99 | 0x80  # 异常响应
        assert resp[1] == 0x01  # Illegal Function

    def test_network_sim_existing_functionality_preserved(self):
        """网络仿真器原有功能不受影响."""
        sim = NetworkSimulator(enabled=True)
        sim._profile = NetworkProfile(latency_ms=10.0, packet_loss_rate=0.5)
        # should_drop 仍然工作
        sim._profile.packet_loss_rate = 1.0
        assert sim.should_drop() is True
        sim._profile.packet_loss_rate = 0.0
        assert sim.should_drop() is False

    def test_state_machine_existing_transitions_preserved(self):
        """状态机原有转换规则不受影响."""
        sm = DeviceStateMachine(device_id="test")
        # STOP → STARTING → RUN
        assert sm.trigger("start") is True
        assert sm.get_state() == DeviceState.STARTING
        # 不满足最小启动时间，不能转到 RUN
        assert sm.can_trigger("startup_complete") is False
        assert sm.trigger("startup_complete") is False

    def test_modbus_err_response_preserved(self):
        """Modbus 异常响应方法原有行为不受影响."""
        server = ModbusTcpServer()
        # 非法功能码
        resp = server._err_response(0x99, server._EX_ILLEGAL_FUNCTION)
        assert resp == bytes([0x99 | 0x80, 0x01])
        # 非法地址
        resp = server._err_response(0x03, server._EX_ILLEGAL_DATA_ADDRESS)
        assert resp == bytes([0x83, 0x02])
        # 非法数据值
        resp = server._err_response(0x06, server._EX_ILLEGAL_DATA_VALUE)
        assert resp == bytes([0x86, 0x03])
