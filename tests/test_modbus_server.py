"""Modbus TCP 服务端核心方法单元测试（无网络）。

覆盖 _read_regs（FC03 读保持寄存器）、_write_single（FC06 写单个寄存器）、
_read_bits（FC01 读线圈）：正常路径 + 边界条件。直接调用内部方法，
使用内存 ModbusDataStore，不绑定端口、不发包。
"""

import struct

from protoforge.models.device import DataType, DeviceConfig, PointConfig
from protoforge.protocols.modbus.server import ModbusTcpServer


def _make_config(device_id: str) -> DeviceConfig:
    return DeviceConfig(
        id=device_id,
        name="Server Unit Test",
        protocol="modbus_tcp",
        points=[
            PointConfig(
                name="reg0", address="0", data_type=DataType.UINT16, access="rw", generator_type="fixed", fixed_value=0
            ),
            PointConfig(
                name="reg1", address="1", data_type=DataType.UINT16, access="rw", generator_type="fixed", fixed_value=0
            ),
            PointConfig(
                name="coil0",
                address="0",
                data_type=DataType.BOOL,
                access="rw",
                generator_type="fixed",
                fixed_value=False,
            ),
        ],
    )


def _server() -> ModbusTcpServer:
    server = ModbusTcpServer()
    server.set_device_state_provider(lambda device_id: "run")
    config = _make_config("dev1")
    server._slave_map[config.id] = 1
    server._device_configs[config.id] = config
    return server


class TestReadHoldingRegisters:
    def test_fc03_reads_seeded_registers(self):
        """正常路径：FC03 读出预置的保持寄存器值。"""
        server = _server()
        store = server._get_data_store(1)
        store.set_point(3, 0, 0x1234)
        store.set_point(3, 1, 0x00FF)
        data = struct.pack(">HH", 0, 2)
        assert server._read_regs(0x03, data, store, 3, 125, 1, "read-holding") == bytes(
            [0x03, 4, 0x12, 0x34, 0x00, 0xFF]
        )

    def test_fc03_short_frame_is_rejected(self):
        """边界：PDU 不足 4 字节 → 异常 0x03。"""
        server = _server()
        store = server._get_data_store(1)
        assert server._read_regs(0x03, b"\x00\x00\x00", store, 3, 125, 1, "read-holding") == bytes([0x83, 0x03])

    def test_fc03_zero_and_over_max_count_rejected(self):
        """边界：count=0 或超过 max_count → 异常 0x03。"""
        server = _server()
        store = server._get_data_store(1)
        assert server._read_regs(0x03, struct.pack(">HH", 0, 0), store, 3, 125, 1, "x") == bytes([0x83, 0x03])
        assert server._read_regs(0x03, struct.pack(">HH", 0, 126), store, 3, 125, 1, "x") == bytes([0x83, 0x03])


class TestWriteSingleRegister:
    def test_fc06_writes_and_echoes(self):
        """正常路径：FC06 写入 store 并原样回显请求。"""
        server = _server()
        store = server._get_data_store(1)
        data = struct.pack(">HH", 0, 0x00FF)
        assert server._write_single(0x06, data, [store], False, 1, "write-single") == bytes([0x06]) + data
        assert store.get_point(3, 0) == 0x00FF

    def test_fc06_broadcast_returns_none(self):
        """正常路径：广播写入无响应但落盘。"""
        server = _server()
        store = server._get_data_store(1)
        data = struct.pack(">HH", 1, 0x0001)
        assert server._write_single(0x06, data, [store], True, 1, "write-single") is None
        assert store.get_point(3, 1) == 0x0001

    def test_fc06_short_frame_is_rejected(self):
        """边界：PDU 不足 4 字节 → 异常 0x03，store 不变。"""
        server = _server()
        store = server._get_data_store(1)
        assert server._write_single(0x06, b"\x00\x01", [store], False, 1, "x") == bytes([0x86, 0x03])
        assert store.get_point(3, 1) == 0

    def test_fc05_illegal_value_is_rejected(self):
        """边界：FC05 值非 0xFF00/0x0000 → 异常 0x03，线圈不变。"""
        server = _server()
        store = server._get_data_store(1)
        data = struct.pack(">HH", 0, 0x1234)
        assert server._write_single(0x05, data, [store], False, 1, "write-coil") == bytes([0x85, 0x03])
        assert store.get_coil(0) == 0


class TestReadCoils:
    def test_fc01_reads_bit_packing(self):
        """正常路径：FC01 按位打包线圈状态（LSB 优先）。"""
        server = _server()
        store = server._get_data_store(1)
        store.set_coil(0, 1)
        store.set_coil(2, 1)
        data = struct.pack(">HH", 0, 3)
        assert server._read_bits(0x01, data, store, store.get_coil, 2000, 1, "read-coils") == bytes(
            [0x01, 1, 0b00000101]
        )

    def test_fc01_zero_count_is_rejected(self):
        """边界：count=0 → 异常 0x03。"""
        server = _server()
        store = server._get_data_store(1)
        data = struct.pack(">HH", 0, 0)
        assert server._read_bits(0x01, data, store, store.get_coil, 2000, 1, "x") == bytes([0x81, 0x03])


class TestErrorResponse:
    def test_exception_frame_shape(self):
        """异常帧 = 功能码|0x80 + 异常码。"""
        server = _server()
        assert server._err_response(0x03, 0x02) == bytes([0x83, 0x02])
        assert server._err_response(0x06, 0x03) == bytes([0x86, 0x03])
