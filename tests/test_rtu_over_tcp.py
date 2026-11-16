"""严格 RTU over TCP 从站测试（v1.16.2，用户反馈：串口服务器透传场景）。

背景：v1.11.1 的 tcp_bridge 说 MBAP 帧——RTU 帧客户端（pymodbus framer=RTU
over TCP、串口服务器透传）连不上。本版补 mode=rtu_over_tcp：RTU 帧
（addr+PDU+CRC16，无 MBAP）直接走 TCP 字节流。
"""

import asyncio

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.modbus.rtu_server import ModbusRtuServer

pymodbus_client = pytest.importorskip("pymodbus")


def _device(device_id="rtu-tcp-1"):
    return DeviceConfig(
        id=device_id,
        name="RTU over TCP 测试",
        protocol="modbus_rtu",
        points=[
            PointConfig(name="temperature", address="0", data_type="float32",
                        access="rw", generator_type="fixed", fixed_value=25.5),
            PointConfig(name="switch_state", address="4", data_type="bool",
                        access="rw", generator_type="fixed", fixed_value=True),
        ],
        protocol_config={"mode": "rtu_over_tcp"},
    )


@pytest.mark.asyncio
async def test_slave_rtu_over_tcp_with_pymodbus_rtu_framer():
    """pymodbus RTU-framer 客户端（串口服务器透传语义）直连从站读写。

    FIXED(v1.16.2): pymodbus 同步客户端必须跑在线程里——直接在测试协程里
    调用会阻塞事件循环，从站协程被饿死收不到请求（表现为 No response）。
    """
    from pymodbus.client import ModbusTcpClient
    from pymodbus.framer import FramerType
    from tests.wire_golden_harness import free_tcp_port

    slave = ModbusRtuServer()
    port = free_tcp_port()
    await slave.start({"host": "127.0.0.1", "port": port,
                       "mode": "rtu_over_tcp", "rtu_over_tcp_port": port,
                       "baudrate": 9600, "parity": "N", "stopbits": 1, "bytesize": 8})
    port = slave._rtu_over_tcp_port  # 端口被占时 _find_available_port 顺延，以实际值为准
    await slave.create_device(_device())
    await slave.write_point("rtu-tcp-1", "temperature", 25.5)

    import struct

    def _pymodbus_session(p: int) -> dict:
        """完整 pymodbus 同步会话（独立线程内运行，含连接重试）。"""
        import time
        client = ModbusTcpClient("127.0.0.1", port=p, framer=FramerType.RTU)
        for _ in range(10):
            if client.connect():
                break
            time.sleep(0.3)
        assert client.connected, "RTU-framer TCP client failed to connect"
        out = {}
        try:
            rr = client.read_holding_registers(address=0, count=2, device_id=1)
            assert not rr.isError(), rr
            out["temperature"] = struct.unpack(">f", struct.pack(">HH", *rr.registers))[0]
            wr = client.write_coil(address=4, value=False, device_id=1)
            assert not wr.isError(), wr
            out["coil_written"] = True
        finally:
            client.close()
        return out

    result = await asyncio.to_thread(_pymodbus_session, port)
    assert result["temperature"] == pytest.approx(25.5, abs=0.01)
    assert result["coil_written"] is True

    vals = {pv.name: pv.value for pv in await slave.read_points("rtu-tcp-1")}
    assert vals["switch_state"] in (False, 0)
    await slave.stop()


@pytest.mark.asyncio
async def test_master_rtu_over_tcp_loopback():
    """ProtoForge 自家主站（mode=rtu_over_tcp）↔ 从站互连采集遥控。"""
    from protoforge.protocols.master.modbus_master import ModbusMasterServer
    from tests.wire_golden_harness import free_tcp_port

    slave = ModbusRtuServer()
    port = free_tcp_port()
    await slave.start({"host": "127.0.0.1", "port": port,
                       "mode": "rtu_over_tcp", "rtu_over_tcp_port": port,
                       "baudrate": 9600, "parity": "N", "stopbits": 1, "bytesize": 8})
    await slave.create_device(_device("rtu-slave-1"))
    await slave.write_point("rtu-slave-1", "temperature", 30.25)

    master = ModbusMasterServer()
    await master.start({})
    await master.create_device(DeviceConfig(
        id="m1", name="M", protocol="modbus_master",
        protocol_config={"host": "127.0.0.1", "port": port, "mode": "rtu_over_tcp",
                         "slave_id": 1, "scan_interval": 0.2, "timeout": 1.0},
        points=[
            PointConfig(name="temperature", address="0", data_type="float32"),
            PointConfig(name="switch_state", address="4", data_type="bool"),
        ],
    ))
    for _ in range(40):
        st = master.get_master_status("m1")
        if st.get("poll_ok", 0) >= 1 and not st.get("last_error"):
            break
        await asyncio.sleep(0.25)
    assert st["poll_ok"] >= 1 and not st["last_error"], st

    pvs = {pv.name: pv for pv in await master.read_points("m1")}
    assert pvs["temperature"].value == pytest.approx(30.25, abs=0.01)

    # 遥控：写远端 float 点位
    assert await master.write_point("m1", "temperature", 88.8) is True
    for _ in range(40):
        slave_vals = {pv.name: pv.value for pv in await slave.read_points("rtu-slave-1")}
        if slave_vals.get("temperature") == pytest.approx(88.8, abs=0.01):
            break
        await asyncio.sleep(0.25)
    slave_vals = {pv.name: pv.value for pv in await slave.read_points("rtu-slave-1")}
    assert slave_vals["temperature"] == pytest.approx(88.8, abs=0.01)
    await master.stop()
    await slave.stop()

