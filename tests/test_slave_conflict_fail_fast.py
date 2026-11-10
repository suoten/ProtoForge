"""从站地址冲突 fail-fast 回归测试（v1.13.2）。

背景（用户实测）：AB MicroLogix 模板显式 slave_id=4，demo 环境里已有设备占用
4 号从站（ph_value@holding[0-1] 与模板 prog_mode@holding[0-0] 重叠）→ 协议层
注册抛 ValueError，但 engine.create_device 把它吞成 WARNING，设备照样"创建
成功"——半残状态：后续写入全部 400 "protocol server rejected"、外部 Modbus
客户端读不到这台设备，而原因只存在于日志。

修复后行为：
1. 协议层注册 ValueError → 回滚引擎内设备 → 向上抛出（API 返回 400 带冲突
   详情，报错含建议的空闲从站号，MCP/AI 可据此自动重试）；
2. 24 个 modbus/modbus_rtu 模板不再写死 slave_id（协议层自动分配空闲号）；
3. SDK HTTPStatusError 消息附带 API 响应体 detail（AI 拿到可执行错误信息）。
"""

import httpx
import pytest

from protoforge.engine.engine import SimulationEngine
from protoforge.models.device import DataType, DeviceConfig, PointConfig
from protoforge.protocols.base import ProtocolStatus
from protoforge.protocols.modbus.server import ModbusTcpServer
from protoforge.sdk import AsyncProtoForgeClient, ProtoForgeClient


def _ab_like_config(device_id: str, slave_id: int = 4) -> DeviceConfig:
    """AB MicroLogix 形状的设备：HR0 uint16 + 线圈 bool + HR4 int32 + HR6 float32。"""
    return DeviceConfig(
        id=device_id,
        name="测试PLC",
        protocol="modbus_tcp",
        points=[
            PointConfig(name="prog_mode", address="0", data_type=DataType.UINT16,
                        access="rw", generator_type="fixed", fixed_value=1),
            PointConfig(name="i0_0", address="1", data_type=DataType.BOOL,
                        access="rw", generator_type="fixed", fixed_value=False),
            PointConfig(name="o0_0", address="3", data_type=DataType.BOOL,
                        access="rw", generator_type="fixed", fixed_value=True),
            PointConfig(name="n7_0", address="4", data_type=DataType.INT32,
                        access="rw", generator_type="random"),
            PointConfig(name="f8_0", address="6", data_type=DataType.FLOAT32,
                        access="rw", generator_type="random"),
        ],
        protocol_config={"slave_id": slave_id},
    )


class TestModbusServerConflict:
    async def test_conflict_raises_and_no_partial_registration(self):
        server = ModbusTcpServer()
        server.set_device_state_provider(lambda device_id: "run")
        await server.create_device(_ab_like_config("dev-a", slave_id=4))

        with pytest.raises(ValueError, match="已被其他设备占用"):
            await server.create_device(_ab_like_config("dev-b", slave_id=4))

        # 半注册防护：冲突设备不留下 behavior / 从站映射
        assert "dev-b" not in server._behaviors
        assert "dev-b" not in server._slave_map

    async def test_registered_device_writable(self):
        """注册成功的设备写入正常（修复前半残设备的对照组）。"""
        server = ModbusTcpServer()
        server.set_device_state_provider(lambda device_id: "run")
        await server.create_device(_ab_like_config("dev-ok", slave_id=5))
        assert await server.write_point("dev-ok", "f8_0", 66.6) is True


class _RejectingServer:
    """模拟协议层注册失败（如从站冲突）。"""

    status = ProtocolStatus.RUNNING

    async def create_device(self, config):
        raise ValueError("从站地址 4 已被其他设备占用，且点位地址存在重叠。"
                         "请修改本设备的从站地址（如改为 11）")


class TestEngineRollback:
    async def test_engine_rolls_back_on_protocol_valueerror(self):
        engine = SimulationEngine()
        engine._protocol_servers["modbus_tcp"] = _RejectingServer()
        cfg = _ab_like_config("conflict-dev")

        with pytest.raises(ValueError, match="从站地址"):
            await engine.create_device(cfg)

        # 关键回归点：半残设备必须从引擎移除，不允许"创建成功但协议层没注册"
        assert "conflict-dev" not in engine._devices

    async def test_generic_protocol_error_keeps_backward_compat(self):
        """非 ValueError 异常维持旧行为（warning + 设备保留），不惊动普通部署。"""
        class _BrokenServer:
            status = ProtocolStatus.RUNNING

            async def create_device(self, config):
                raise RuntimeError("internal boom")

        engine = SimulationEngine()
        engine._protocol_servers["modbus_tcp"] = _BrokenServer()
        cfg = _ab_like_config("boom-dev")

        info = await engine.create_device(cfg)
        assert info.id == "boom-dev"
        assert "boom-dev" in engine._devices  # 旧行为保留


def _detail_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(400, json={
        "code": 400,
        "message": "Write failed - protocol server rejected the write",
        "detail": "从站地址 4 已被其他设备占用，且点位地址存在重叠。请修改从站地址（如改为 11）",
    })


class TestSDKErrorDetail:
    def test_sync_error_includes_api_detail(self):
        client = ProtoForgeClient("http://localhost:1")
        client._client = httpx.Client(transport=httpx.MockTransport(_detail_handler))
        with pytest.raises(httpx.HTTPStatusError) as exc:
            client.write_point("dev", "prog_mode", 1)
        assert "已被其他设备占用" in str(exc.value)
        assert "改为 11" in str(exc.value)

    async def test_async_error_includes_api_detail(self):
        client = AsyncProtoForgeClient("http://localhost:1")
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(_detail_handler))
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await client.write_point("dev", "prog_mode", 1)
        assert "已被其他设备占用" in str(exc.value)
