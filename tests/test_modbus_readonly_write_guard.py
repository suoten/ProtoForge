"""FIXED: Modbus 外部写入 access 只读校验回归测试。

背景：此前外部 Modbus 客户端（FC05/06/0F/10/16/17）写入时不校验点位访问模式，
界面上标为只读（access='r'）的点位仍可被外部写成功——与平台侧写入路径
（ModbusServer.write_point 会拒绝 access='r'）语义不一致。

修复后行为：
- 外部写命中 access='r' 点位 → 返回异常码 0x01（ILLEGAL FUNCTION），store 不变，
  不触发 _notify_external_write 双向传播；
- access='w'/'rw' 点位 → 正常写入并传播（双向写链路不受影响）；
- 广播写入命中只读点位 → 无响应（广播语义），写入被丢弃。
"""

import asyncio
import struct

import pytest

from protoforge.models.device import DataType, DeviceConfig, PointConfig
from protoforge.protocols.modbus.rtu_server import ModbusRtuServer
from protoforge.protocols.modbus.server import ModbusTcpServer


def _make_config(device_id: str) -> DeviceConfig:
    """两个点位：rw_point（可写，holding addr 0）、ro_point（只读，holding addr 10）。
    另有 ro_coil（只读线圈，addr 0）用于 FC05/0F 校验。"""
    return DeviceConfig(
        id=device_id,
        name="Readonly Guard Test",
        protocol="modbus_tcp",
        points=[
            PointConfig(name="rw_point", address="0", data_type=DataType.UINT16,
                        access="rw", generator_type="fixed", fixed_value=0),
            PointConfig(name="ro_point", address="10", data_type=DataType.UINT16,
                        access="r", generator_type="fixed", fixed_value=0),
            PointConfig(name="ro_coil", address="0", data_type=DataType.BOOL,
                        access="r", generator_type="fixed", fixed_value=False),
        ],
    )


def _register(server, config: DeviceConfig, slave_id: int = 1) -> None:
    server._slave_map[config.id] = slave_id
    server._device_configs[config.id] = config
    server._get_data_store(slave_id)


# ─── Modbus TCP ───────────────────────────────────────────────────────────────

class TestTcpReadonlyWriteGuard:
    def _server(self) -> ModbusTcpServer:
        server = ModbusTcpServer()
        server.set_device_state_provider(lambda device_id: "run")
        _register(server, _make_config("dev1"))
        return server

    def test_fc06_write_readonly_rejected(self):
        """FC06 写只读点位（addr 10）→ 异常码 0x01，store 不变."""
        server = self._server()
        data = struct.pack(">HH", 10, 123)
        resp = server._process_modbus_frame(1, 0x06, data)
        assert resp == bytes([0x86, 0x01])
        assert server._get_data_store(1).get_point(3, 10) == 0

    def test_fc06_write_rw_ok(self):
        """FC06 写可写点位（addr 0）→ 正常响应，store 更新（双向写链路不受影响）."""
        server = self._server()
        data = struct.pack(">HH", 0, 123)
        resp = server._process_modbus_frame(1, 0x06, data)
        assert resp == bytes([0x06]) + data[:4]
        assert server._get_data_store(1).get_point(3, 0) == 123

    def test_fc05_write_readonly_coil_rejected(self):
        """FC05 写只读线圈 → 异常码 0x01."""
        server = self._server()
        data = struct.pack(">HH", 0, 0xFF00)
        resp = server._process_modbus_frame(1, 0x05, data)
        assert resp == bytes([0x85, 0x01])
        assert server._get_data_store(1).get_coil(0) == 0

    def test_fc0f_write_readonly_coil_range_rejected(self):
        """FC0F 写线圈范围覆盖只读线圈（addr 0-1）→ 整体拒绝."""
        server = self._server()
        data = struct.pack(">HHB", 0, 2, 1) + b"\x03"
        resp = server._process_modbus_frame(1, 0x0F, data)
        assert resp == bytes([0x8F, 0x01])
        assert server._get_data_store(1).get_coil(0) == 0

    def test_fc10_write_spanning_readonly_rejected(self):
        """FC10 写寄存器范围部分覆盖只读点位（addr 9-10）→ 整体拒绝."""
        server = self._server()
        data = struct.pack(">HHB", 9, 2, 4) + struct.pack(">HH", 1, 2)
        resp = server._process_modbus_frame(1, 0x10, data)
        assert resp == bytes([0x90, 0x01])
        assert server._get_data_store(1).get_point(3, 9) == 0
        assert server._get_data_store(1).get_point(3, 10) == 0

    def test_fc10_write_rw_only_ok(self):
        """FC10 只写可写范围（addr 0-1）→ 正常."""
        server = self._server()
        data = struct.pack(">HHB", 0, 2, 4) + struct.pack(">HH", 7, 8)
        resp = server._process_modbus_frame(1, 0x10, data)
        assert resp == bytes([0x10]) + data[:4]
        assert server._get_data_store(1).get_point(3, 0) == 7

    def test_fc16_mask_write_readonly_rejected(self):
        """FC16 掩码写只读点位 → 异常码 0x01."""
        server = self._server()
        data = struct.pack(">HHH", 10, 0x0000, 0xFFFF)
        resp = server._process_modbus_frame(1, 0x16, data)
        assert resp == bytes([0x96, 0x01])

    def test_fc17_write_part_readonly_rejected(self):
        """FC17 读写多寄存器：写部分命中只读点位 → 整体拒绝."""
        server = self._server()
        data = struct.pack(">HHHHB", 0, 1, 10, 1, 2) + struct.pack(">H", 5)
        resp = server._process_modbus_frame(1, 0x17, data)
        assert resp == bytes([0x97, 0x01])
        assert server._get_data_store(1).get_point(3, 10) == 0

    def test_broadcast_write_readonly_dropped_silently(self):
        """广播写命中只读点位 → 无响应（广播语义），写入被丢弃."""
        server = self._server()
        data = struct.pack(">HH", 10, 123)
        resp = server._process_modbus_frame(0, 0x06, data)
        assert resp is None
        assert server._get_data_store(1).get_point(3, 10) == 0

    def test_w_point_access_still_writable(self):
        """access='w' 点位外部可写（只读校验只针对 access='r'）."""
        config = _make_config("dev1")
        config.points.append(
            PointConfig(name="w_point", address="20", data_type=DataType.UINT16,
                        access="w", generator_type="fixed", fixed_value=0))
        server = ModbusTcpServer()
        server.set_device_state_provider(lambda device_id: "run")
        _register(server, config)
        data = struct.pack(">HH", 20, 99)
        resp = server._process_modbus_frame(1, 0x06, data)
        assert resp == bytes([0x06]) + data[:4]
        assert server._get_data_store(1).get_point(3, 20) == 99

    @pytest.mark.asyncio
    async def test_readonly_reject_skips_notify(self):
        """只读拒绝后不触发 _notify_external_write 双向传播."""
        server = self._server()
        notified = []
        server._on_write = lambda d, p, v: notified.append((d, p, v))
        server._process_modbus_frame(1, 0x06, struct.pack(">HH", 10, 123))
        await asyncio.sleep(0.05)
        assert notified == []

    @pytest.mark.asyncio
    async def test_rw_write_still_notifies(self):
        """可写点位外部写仍触发双向传播回调（回归保护）."""
        server = self._server()
        notified = []
        server._on_write = lambda d, p, v: notified.append((d, p, v))
        server._process_modbus_frame(1, 0x06, struct.pack(">HH", 0, 123))
        await asyncio.sleep(0.05)
        assert notified == [("dev1", "rw_point", 123)]


# ─── Modbus RTU ───────────────────────────────────────────────────────────────

class TestRtuReadonlyWriteGuard:
    def _server(self) -> ModbusRtuServer:
        server = ModbusRtuServer()
        server.set_device_state_provider(lambda device_id: "run")
        _register(server, _make_config("dev1"))
        return server

    def test_fc06_write_readonly_rejected(self):
        server = self._server()
        resp = server._process_modbus_frame(1, 0x06, struct.pack(">HH", 10, 123))
        assert resp == bytes([0x86, 0x01])
        assert server._data_stores[1].get_point(3, 10) == 0

    def test_fc06_write_rw_ok(self):
        server = self._server()
        data = struct.pack(">HH", 0, 123)
        resp = server._process_modbus_frame(1, 0x06, data)
        assert resp == bytes([0x06]) + data[:4]
        assert server._data_stores[1].get_point(3, 0) == 123

    def test_fc05_write_readonly_coil_rejected(self):
        server = self._server()
        resp = server._process_modbus_frame(1, 0x05, struct.pack(">HH", 0, 0xFF00))
        assert resp == bytes([0x85, 0x01])
        assert server._data_stores[1].get_coil(0) == 0

    def test_fc10_write_spanning_readonly_rejected(self):
        server = self._server()
        data = struct.pack(">HHB", 9, 2, 4) + struct.pack(">HH", 1, 2)
        resp = server._process_modbus_frame(1, 0x10, data)
        assert resp == bytes([0x90, 0x01])
        assert server._data_stores[1].get_point(3, 10) == 0

    def test_fc16_mask_write_readonly_rejected(self):
        server = self._server()
        resp = server._process_modbus_frame(1, 0x16, struct.pack(">HHH", 10, 0x0000, 0xFFFF))
        assert resp == bytes([0x96, 0x01])

    def test_fc17_write_part_readonly_rejected(self):
        server = self._server()
        data = struct.pack(">HHHHB", 0, 1, 10, 1, 2) + struct.pack(">H", 5)
        resp = server._process_modbus_frame(1, 0x17, data)
        assert resp == bytes([0x97, 0x01])
        assert server._data_stores[1].get_point(3, 10) == 0
