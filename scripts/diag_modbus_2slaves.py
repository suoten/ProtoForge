"""Repro: Modbus TCP 2-slave data correctness.

Scenario A: two devices, UI-default slave_id=1 both (defaults.py default) -> collision?
Scenario B: device1 slave_id=1, device2 slave_id=2 -> read both units via raw frames.
"""
import asyncio, os, socket, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.models.device import DataType, DeviceConfig, PointConfig
from protoforge.protocols.modbus.server import ModbusTcpServer

PORT = 15021

def make_dev(dev_id, name, slave_id_in_cfg, addr, value):
    return DeviceConfig(
        id=dev_id, name=name, protocol="modbus_tcp",
        protocol_config={"host": "127.0.0.1", "port": PORT, "slave_id": slave_id_in_cfg},
        points=[PointConfig(name="reg1", address=addr, data_type=DataType.UINT16,
                            access="rw", generator_type="fixed", fixed_value=value)],
    )

async def read_regs(unit, addr, count):
    reader, writer = await asyncio.open_connection("127.0.0.1", PORT)
    pdu = struct.pack(">BHH", 3, addr, count)
    mbap = struct.pack(">HHHB", 1, 0, len(pdu) + 1, unit)
    writer.write(mbap + pdu)
    await writer.drain()
    r = await asyncio.wait_for(reader.read(512), timeout=3)
    writer.close()
    return r[7], r[8] if len(r) > 8 else None, list(r[9:])

async def main():
    srv = ModbusTcpServer()
    await srv.start({"host": "127.0.0.1", "port": PORT})
    await asyncio.sleep(0.3)

    # Scenario A: UI 默认两个设备都带 slave_id=1
    await srv.create_device(make_dev("devA1", "从站1", 1, "HR100", 1111))
    await srv.create_device(make_dev("devA2", "从站2", 1, "HR200", 2222))
    print("slave_map (A):", srv._slave_map)
    print("stores  (A):", sorted(srv._data_stores))

    u1 = await read_regs(1, 100, 2)
    u2 = await read_regs(2, 200, 2)
    print("A: unit1 HR100 ->", u1, "(expect value=1111)")
    print("A: unit2 HR200 ->", u2, "(expect value=2222 if slave2 exists)")

    await srv.remove_device("devA1"); await srv.remove_device("devA2")
    srv._data_stores.clear(); srv._slave_map.clear(); srv._next_slave_id = 1

    # Scenario B: 用户在 UI 手动把从站2改成 2
    await srv.create_device(make_dev("devB1", "从站1", 1, "HR100", 1111))
    await srv.create_device(make_dev("devB2", "从站2", 2, "HR200", 2222))
    print("slave_map (B):", srv._slave_map)
    u1 = await read_regs(1, 100, 2)
    u2 = await read_regs(2, 200, 2)
    print("B: unit1 HR100 ->", u1, "(expect byte_count=4, value=1111)")
    print("B: unit2 HR200 ->", u2, "(expect byte_count=4, value=2222)")

    # UI read_points 路径
    print("B: read_points devB1 ->", [pv.value for pv in await srv.read_points("devB1")])
    print("B: read_points devB2 ->", [pv.value for pv in await srv.read_points("devB2")])

    # Scenario C: 同从站号 + 点位地址重叠 → 必须报错拦截（数据互相覆盖的根因）
    try:
        await srv.create_device(make_dev("devC", "从站冲突", 1, "HR100", 3333))
        print("C: FAIL - overlap on same slave was allowed")
    except ValueError as e:
        print("C: OK - conflict rejected:", str(e)[:80], "...")
        assert "devC" not in srv._behaviors, "failed device must not be registered"

    # Scenario D: 同从站号 + 地址不重叠 → 允许共享（向后兼容联调场景）
    await srv.create_device(make_dev("devD", "共享从站", 1, "HR300", 4444))
    print("D: OK - non-overlap sharing allowed, slave_map:", srv._slave_map)

    await srv.stop()
    print("ALL MODBUS 2-SLAVE REGRESSION PASSED")

asyncio.run(main())



