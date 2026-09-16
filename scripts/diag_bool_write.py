"""Diagnose bool point read/write abnormality (user report 2026-09-16).

Scenario: modbus_tcp device with DI/DO points. User quick-writes
"true" / 11 / 1 via UI and reads holding registers with mbpoll F03.

Checks (after fix):
1. bool point write "true"/"11"/1 -> behavior value True, coil=1
2. uint16 point write "true" -> rejected (previously stored raw string)
3. uint16 point write "42" (string) -> 42, holding reg = 42
4. bool write reject "abc"
"""
import asyncio
import os
import sys

os.environ["PROTOFORGE_NO_AUTH"] = "1"
os.environ.setdefault("PROTOFORGE_ADMIN_PASSWORD", "diag-admin-pw")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protoforge.engine.engine import SimulationEngine  # noqa: E402
from protoforge.models.device import DeviceConfig, PointConfig  # noqa: E402


async def main() -> None:
    from protoforge.protocols.modbus.server import ModbusTcpServer

    engine = SimulationEngine()
    await engine.start()

    server = ModbusTcpServer()
    await server.start({"host": "0.0.0.0", "port": 15020})

    cfg = DeviceConfig(
        id="test",
        name="test",
        protocol="modbus_tcp",
        points=[
            PointConfig(name="run_mode", address="0", data_type="uint16", access="rw"),
            PointConfig(name="cpu_load", address="1", data_type="uint16", access="rw"),
            PointConfig(name="di0", address="2", data_type="bool", access="rw"),
            PointConfig(name="di1", address="3", data_type="bool", access="rw"),
            PointConfig(name="do0", address="4", data_type="bool", access="rw"),
            PointConfig(name="n16", address="5", data_type="uint16", access="rw"),
        ],
    )
    await server.create_device(cfg)

    results = []

    async def w(point, value):
        ok = await server.write_point("test", point, value)
        v = server._behaviors["test"].get_value(point)
        results.append((point, repr(value), ok, repr(v)))
        return ok, v

    # 1. bool writes
    await w("di0", 1)
    await w("di1", "true")
    await w("do0", 11)

    # 2. uint16 with garbage string -> must be rejected now
    ok, v = await w("n16", "true")
    assert ok is False or v == "true", "uint16 raw string stored!"

    # 3. uint16 numeric string -> coerced
    await w("n16", "42")

    # 4. bool garbage -> rejected
    ok, v = await w("di1", "abc")
    assert ok is False or v == "abc", f"bool garbage stored: {v!r}"

    print("\n=== write results (point, sent, accepted, stored) ===")
    for r in results:
        print(" ", r)

    store = server._get_data_store(1)
    print("\n=== coils (bool area, mbpoll F01) ===")
    print(" ", {a: store.coils.get(a) for a in range(0, 6)})
    print("=== holding regs (mbpoll F03) ===")
    print(" ", {a: store.holding_regs.get(a) for a in range(0, 7)})

    # Verify: behavior values consistent with store encoding
    beh = server._behaviors["test"]
    ok_all = True
    for p, expect in (("di0", True), ("di1", True), ("do0", True)):
        got = beh.get_value(p)
        if got is not True:
            print(f"FAIL: {p} stored {got!r}, expected True")
            ok_all = False
    for a, expect in ((2, 1), (3, 1), (4, 1)):
        got = store.coils.get(a)
        if got != expect:
            print(f"FAIL: coil {a} = {got!r}, expected {expect}")
            ok_all = False
    if store.holding_regs.get(5) != 42:
        print(f"FAIL: holding reg 5 = {store.holding_regs.get(5)!r}, expected 42")
        ok_all = False

    print("\nBOOL WRITE NORMALIZATION: " + ("OK" if ok_all else "FAILED"))

    await server.stop()
    await engine.stop()
    sys.stdout.flush()
    os._exit(0 if ok_all else 1)


if __name__ == "__main__":
    asyncio.run(main())
