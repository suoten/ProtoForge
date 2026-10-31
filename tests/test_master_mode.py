"""v1.9.0 主站模式测试：MasterBase 单元 + 三主站回环集成。

回环拓扑：ProtoForge 自身从站（被测协议实现的黄金用例背书）
← 拨出 ← 主站实现。验证：轮询取值、数据类型解码、写远端、
重连退避、质量标记、优雅停止。
"""

import asyncio

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from tests.wire_golden_harness import free_tcp_port

HOST = "127.0.0.1"


async def _teardown(master, slave):
    for server in (master, slave):
        if server is None:
            continue
        stop_task = asyncio.ensure_future(server.stop())
        try:
            await asyncio.wait_for(asyncio.shield(stop_task), timeout=10)
        except asyncio.TimeoutError:
            pass


async def _wait_first_poll(master, device_id, tries=50):
    for _ in range(tries):
        st = master.get_master_status(device_id)
        if st.get("last_poll_ts", 0) > 0:
            return st
        await asyncio.sleep(0.1)
    return master.get_master_status(device_id)


async def _wait_value(master, device_id, point, expected, tries=30):
    for _ in range(tries):
        pvs = {pv.name: pv for pv in await master.read_points(device_id)}
        if pvs[point].value == expected:
            return
        await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# MasterBase 单元
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_interval_clamped():
    from protoforge.protocols.master.modbus_master import ModbusMasterServer
    m = ModbusMasterServer()
    assert m._scan_interval_of({}) == 1.0
    assert m._scan_interval_of({"scan_interval": 0.01}) == 0.1      # 下限
    assert m._scan_interval_of({"scan_interval": 99999}) == 3600.0  # 上限


@pytest.mark.asyncio
async def test_unreachable_slave_marks_quality_bad():
    """连不上的从站：poll_err 增长、点位质量 bad、last_error 有内容。"""
    from protoforge.protocols.master.modbus_master import ModbusMasterServer
    m = ModbusMasterServer()
    await m.start({})
    await m.create_device(DeviceConfig(
        id="m1", name="M", protocol="modbus_master",
        protocol_config={"host": HOST, "port": free_tcp_port(), "mode": "tcp",
                         "scan_interval": 0.2, "timeout": 0.5},
        points=[PointConfig(name="v", address="HR0", data_type="float32")],
    ))
    for _ in range(20):
        st = m.get_master_status("m1")
        if st["poll_err"] >= 1:
            break
        await asyncio.sleep(0.2)
    st = m.get_master_status("m1")
    assert st["poll_err"] >= 1, st
    assert st["last_error"], st
    pvs = await m.read_points("m1")
    assert pvs[0].quality == "bad"
    await _teardown(m, None)


@pytest.mark.asyncio
async def test_remove_device_cleans_state():
    from protoforge.protocols.master.modbus_master import ModbusMasterServer
    m = ModbusMasterServer()
    await m.start({})
    await m.create_device(DeviceConfig(
        id="m1", name="M", protocol="modbus_master",
        protocol_config={"host": HOST, "port": free_tcp_port(), "mode": "tcp",
                         "scan_interval": 0.2, "timeout": 0.5},
        points=[PointConfig(name="v", address="HR0", data_type="uint16")],
    ))
    await m.remove_device("m1")
    assert "m1" not in m._poll_tasks
    assert "m1" not in m._device_configs
    assert await m.read_points("m1") == []
    assert await m.write_point("m1", "v", 1) is False
    await _teardown(m, None)


@pytest.mark.asyncio
async def test_stop_is_idempotent():
    from protoforge.protocols.master.modbus_master import ModbusMasterServer
    m = ModbusMasterServer()
    await m.start({})
    await m.create_device(DeviceConfig(
        id="m1", name="M", protocol="modbus_master",
        protocol_config={"host": HOST, "port": free_tcp_port(), "mode": "tcp",
                         "scan_interval": 0.2, "timeout": 0.5},
        points=[PointConfig(name="v", address="HR0", data_type="uint16")],
    ))
    await asyncio.wait_for(m.stop(), timeout=10)
    await asyncio.wait_for(m.stop(), timeout=10)  # 幂等
    assert "m1" not in m._poll_tasks


# ---------------------------------------------------------------------------
# Modbus 主站 → 本机 Modbus TCP 从站
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_modbus_master_loopback_read_write():
    from protoforge.protocols.master.modbus_master import ModbusMasterServer
    from protoforge.protocols.modbus.server import ModbusTcpServer

    slave = ModbusTcpServer()
    port = free_tcp_port()
    await slave.start({"host": HOST, "port": port})
    await slave.create_device(DeviceConfig(
        id="slave1", name="S", protocol="modbus_tcp",
        points=[
            PointConfig(name="temp", address="HR0", data_type="float32"),
            PointConfig(name="pressure", address="HR2", data_type="int32"),
            PointConfig(name="pump", address="C0", data_type="bool"),
            PointConfig(name="speed", address="IR0", data_type="uint16"),
        ],
    ))
    await slave.write_point("slave1", "temp", 23.5)
    await slave.write_point("slave1", "pressure", -123456)
    await slave.write_point("slave1", "pump", True)
    await slave.write_point("slave1", "speed", 1470)

    master = ModbusMasterServer()
    await master.start({})
    await master.create_device(DeviceConfig(
        id="m1", name="M", protocol="modbus_master",
        protocol_config={"host": HOST, "port": port, "mode": "tcp", "slave_id": 1,
                         "scan_interval": 0.2, "timeout": 2.0},
        points=[
            PointConfig(name="temp", address="HR0", data_type="float32"),
            PointConfig(name="pressure", address="HR2", data_type="int32"),
            PointConfig(name="pump", address="C0", data_type="bool"),
            PointConfig(name="speed", address="IR0", data_type="uint16"),
        ],
    ))
    st = await _wait_first_poll(master, "m1")
    assert st["poll_ok"] >= 1 and not st["last_error"], st

    pvs = {pv.name: pv for pv in await master.read_points("m1")}
    assert pvs["temp"].value == pytest.approx(23.5, abs=0.01)
    assert pvs["pressure"].value == -123456
    assert pvs["pump"].value is True
    assert pvs["speed"].value == 1470
    assert all(pv.quality == "good" for pv in pvs.values())

    # 写远端：主站下发 → 从站存储可读
    assert await master.write_point("m1", "temp", 66.6) is True
    assert await master.write_point("m1", "pump", False) is True
    await _wait_value(master, "m1", "temp", 66.6)
    slave_vals = {pv.name: pv.value for pv in await slave.read_points("slave1")}
    assert slave_vals["temp"] == pytest.approx(66.6, abs=0.01)
    assert slave_vals["pump"] in (0, False)

    st = master.get_master_status("m1")
    assert st["connected"] is True
    await _teardown(master, slave)


@pytest.mark.asyncio
async def test_modbus_master_rtu_over_tcp_loopback():
    """RTU-over-TCP：对字节级 RTU stub 从站验证 FramerRTU 帧 + CRC16。"""
    import struct as _struct
    from protoforge.protocols.master.modbus_master import ModbusMasterServer

    async def _rtu_stub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while True:
                req = await reader.readexactly(8)  # addr fc addr2 cnt2 crc2
                addr, fc = req[0], req[1]
                start = _struct.unpack(">H", req[2:4])[0]
                recv_crc = _struct.unpack("<H", req[6:8])[0]
                if recv_crc != _crc16(req[:6]):
                    continue
                if fc == 3 and start == 10:
                    body = bytes([addr, fc, 2]) + _struct.pack(">H", 777)
                elif fc == 6:
                    body = req[:6]
                else:
                    body = bytes([addr, fc | 0x80, 0x02])  # 非法地址异常
                resp = body + _struct.pack("<H", _crc16(body))
                writer.write(resp)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(_rtu_stub, HOST, 0)
    port = server.sockets[0].getsockname()[1]

    master = ModbusMasterServer()
    await master.start({})
    await master.create_device(DeviceConfig(
        id="m1", name="M", protocol="modbus_master",
        protocol_config={"host": HOST, "port": port, "mode": "rtu_over_tcp",
                         "slave_id": 1, "scan_interval": 0.2, "timeout": 2.0},
        points=[PointConfig(name="v", address="HR10", data_type="uint16")],
    ))
    try:
        st = await _wait_first_poll(master, "m1")
        assert st["poll_ok"] >= 1 and not st["last_error"], st
        await _wait_value(master, "m1", "v", 777)
        pvs = {pv.name: pv for pv in await master.read_points("m1")}
        assert pvs["v"].value == 777 and pvs["v"].quality == "good"
        # 写单寄存器（FC06）→ stub 回显请求帧
        assert await master.write_point("m1", "v", 888) is True
    finally:
        # 先停主站（关闭客户端连接），再关 stub 服务器——
        # py3.12 的 wait_closed 会等所有连接断开，顺序颠倒会永久挂起
        await _teardown(master, None)
        server.close()
        try:
            await asyncio.wait_for(server.wait_closed(), timeout=5)
        except asyncio.TimeoutError:
            pass


def _crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


# ---------------------------------------------------------------------------
# S7 主站 → 本机 S7 从站
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_s7_master_loopback_read_write():
    from protoforge.protocols.master.s7_master import S7MasterServer
    from protoforge.protocols.s7.server import S7Server

    slave = S7Server()
    port = free_tcp_port()
    await slave.start({"host": HOST, "port": port, "rack": 0, "slot": 0})
    await slave.create_device(DeviceConfig(
        id="plc1", name="P", protocol="s7",
        points=[
            PointConfig(name="temp", address="DB1.DBD0", data_type="float32"),
            PointConfig(name="counter", address="DB1.DBW4", data_type="uint16"),
            PointConfig(name="pump", address="DB1.DBX6.0", data_type="bool"),
            PointConfig(name="setpoint", address="MD10", data_type="float32"),
        ],
    ))
    await slave.write_point("plc1", "temp", 42.5)
    await slave.write_point("plc1", "counter", 1234)
    await slave.write_point("plc1", "pump", True)
    await slave.write_point("plc1", "setpoint", 3.75)

    master = S7MasterServer()
    await master.start({})
    await master.create_device(DeviceConfig(
        id="m1", name="M", protocol="s7_master",
        protocol_config={"host": HOST, "port": port, "rack": 0, "slot": 0,
                         "scan_interval": 0.2, "timeout": 2.0},
        points=[
            PointConfig(name="temp", address="DB1.DBD0", data_type="float32"),
            PointConfig(name="counter", address="DB1.DBW4", data_type="uint16"),
            PointConfig(name="pump", address="DB1.DBX6.0", data_type="bool"),
            PointConfig(name="setpoint", address="MD10", data_type="float32"),
        ],
    ))
    st = await _wait_first_poll(master, "m1")
    assert st["poll_ok"] >= 1 and not st["last_error"], st

    pvs = {pv.name: pv for pv in await master.read_points("m1")}
    assert pvs["temp"].value == pytest.approx(42.5, abs=0.01)
    assert pvs["counter"].value == 1234
    assert pvs["pump"].value is True
    assert pvs["setpoint"].value == pytest.approx(3.75, abs=0.001)

    assert await master.write_point("m1", "temp", 99.5) is True
    assert await master.write_point("m1", "pump", False) is True
    await _wait_value(master, "m1", "temp", 99.5)
    slave_vals = {pv.name: pv.value for pv in await slave.read_points("plc1")}
    assert slave_vals["temp"] == pytest.approx(99.5, abs=0.01)
    assert slave_vals["pump"] in (0, False)
    await _teardown(master, slave)


# ---------------------------------------------------------------------------
# IEC 104 主站 → 本机 IEC 104 从站
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_iec104_master_loopback_gi_and_control():
    from protoforge.protocols.iec104.server import IEC104Server
    from protoforge.protocols.master.iec104_master import IEC104MasterServer

    slave = IEC104Server()
    port = free_tcp_port()
    await slave.start({"host": HOST, "port": port, "common_address": 1,
                       "scan_interval": 1.0})
    await slave.create_device(DeviceConfig(
        id="rtu1", name="R", protocol="iec104",
        points=[
            PointConfig(name="bus_voltage", address="1", data_type="float32"),
            PointConfig(name="breaker", address="3", data_type="bool"),
        ],
    ))
    await slave.write_point("rtu1", "bus_voltage", 220.5)
    await slave.write_point("rtu1", "breaker", True)

    master = IEC104MasterServer()
    await master.start({})
    await master.create_device(DeviceConfig(
        id="m1", name="M", protocol="iec104_master",
        protocol_config={"host": HOST, "port": port, "common_address": 1,
                         "scan_interval": 0.5, "timeout": 2.0},
        points=[
            PointConfig(name="bus_voltage", address="1", data_type="float32"),
            PointConfig(name="breaker", address="3", data_type="bool"),
        ],
    ))
    st = await _wait_first_poll(master, "m1", tries=60)
    assert st["poll_ok"] >= 1 and not st["last_error"], st

    pvs = {pv.name: pv for pv in await master.read_points("m1")}
    assert pvs["bus_voltage"].value == pytest.approx(220.5, abs=0.01)
    assert pvs["breaker"].value is True

    # 遥控（C_SC 直接执行，双确认）
    assert await master.write_point("m1", "breaker", False) is True
    await _wait_value(master, "m1", "breaker", False, tries=40)
    slave_vals = {pv.name: pv.value for pv in await slave.read_points("rtu1")}
    assert slave_vals["breaker"] in (0, False)
    await _teardown(master, slave)


# ---------------------------------------------------------------------------
# 引擎级集成：主站设备点位进现有断言体系
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_master_device_read_write():
    from protoforge.engine.engine import SimulationEngine
    from protoforge.protocols.master.modbus_master import ModbusMasterServer
    from protoforge.protocols.modbus.server import ModbusTcpServer

    eng = SimulationEngine()
    eng.register_protocol(ModbusTcpServer())
    eng.register_protocol(ModbusMasterServer())
    await eng.start()
    try:
        port = free_tcp_port()
        await eng.create_device(DeviceConfig(
            id="slave1", name="S", protocol="modbus_tcp",
            protocol_config={"host": HOST, "port": port},
            points=[PointConfig(name="temp", address="HR0", data_type="float32",
                                generator_type="fixed", fixed_value=12.5)],
        ))
        await eng.start_device("slave1")
        await eng.create_device(DeviceConfig(
            id="master1", name="M", protocol="modbus_master",
            protocol_config={"host": HOST, "port": port, "mode": "tcp", "slave_id": 1,
                             "scan_interval": 0.2, "timeout": 2.0},
            points=[PointConfig(name="temp", address="HR0", data_type="float32")],
        ))
        await eng.start_device("master1")

        for _ in range(30):
            pvs = await eng.read_device_points("master1")
            if abs(pvs[0].value - 12.5) < 0.01:
                break
            await asyncio.sleep(0.2)
        pvs = await eng.read_device_points("master1")
        assert abs(pvs[0].value - 12.5) < 0.01, pvs

        assert await eng.write_device_point("master1", "temp", 77.7) is True
        for _ in range(30):
            sv = await eng.read_device_points("slave1")
            if abs(sv[0].value - 77.7) < 0.01:
                break
            await asyncio.sleep(0.2)
        sv = await eng.read_device_points("slave1")
        assert abs(sv[0].value - 77.7) < 0.01, sv
    finally:
        await asyncio.wait_for(eng.stop(), timeout=15)
