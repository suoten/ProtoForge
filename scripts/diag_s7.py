"""
ProtoForge S7 Protocol Diagnostic Test

Tests S7 server Read/Write with snap7 client, simulating what a real user does.
Verifies data integrity for bool/uint16/float32 types at various DB offsets.

Usage:
    python scripts/diag_s7.py
"""

import asyncio
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import snap7

from protoforge.models.device import DeviceConfig, PointConfig, DataType
from protoforge.protocols.s7.server import S7Server

HOST = "127.0.0.1"
PORT = 1102  # Use non-standard port to avoid conflicts


async def start_server() -> S7Server:
    """Create and start the ProtoForge S7 server with a test device."""
    server = S7Server()

    config = DeviceConfig(
        id="test-s7-1200",
        name="Test S7-1200",
        protocol="s7",
        points=[
            PointConfig(
                name="run_status",
                address="DB1.DBX0.0",
                data_type=DataType.BOOL,
                access="rw",
                generator_type="fixed",
                fixed_value=True,
            ),
            PointConfig(
                name="cpu_load",
                address="DB1.DBW2",
                data_type=DataType.UINT16,
                unit="%",
                access="rw",
                generator_type="fixed",
                fixed_value=42,
            ),
            PointConfig(
                name="temperature",
                address="DB1.DBD4",
                data_type=DataType.FLOAT32,
                unit="C",
                access="rw",
                generator_type="fixed",
                fixed_value=55.5,
            ),
            PointConfig(
                name="speed_setpoint",
                address="DB1.DBD8",
                data_type=DataType.FLOAT32,
                unit="RPM",
                access="rw",
                generator_type="fixed",
                fixed_value=1500.0,
            ),
            PointConfig(
                name="actual_speed",
                address="DB1.DBD12",
                data_type=DataType.FLOAT32,
                unit="RPM",
                access="rw",
                generator_type="fixed",
                fixed_value=1480.0,
            ),
        ],
        protocol_config={
            "rack": 0,
            "slot": 1,
            "optimized_db": True,  # S7-1200 uses optimized DB access
        },
    )

    await server.create_device(config)
    await server.start({"host": HOST, "port": PORT})
    await asyncio.sleep(0.3)
    return server


def run_tests() -> list[tuple[str, bool, str]]:
    """Execute all S7 test cases using snap7 client."""
    results: list[tuple[str, bool, str]] = []

    client = snap7.client.Client()
    try:
        client.connect(HOST, 0, 1, PORT)
        results.append(("Connect", True, f"Connected to {HOST}:{PORT}"))

        # ---- Test 1: Read BOOL (DB1.DBX0.0 = run_status, expect True) ----
        try:
            data = client.db_read(1, 0, 1)  # DB1, offset 0, 1 byte
            val = bool(data[0] & 0x01)
            if val:
                results.append(("Read BOOL DB1.DBX0.0", True, f"value={val} (expect True)"))
            else:
                results.append(("Read BOOL DB1.DBX0.0", False, f"value={val} (expect True), raw={data.hex()}"))
        except Exception as exc:
            results.append(("Read BOOL DB1.DBX0.0", False, str(exc)))

        # ---- Test 2: Read UINT16 (DB1.DBW2 = cpu_load, expect 42) ----
        try:
            data = client.db_read(1, 2, 2)  # DB1, offset 2, 2 bytes
            val = struct.unpack(">H", data)[0]
            if val == 42:
                results.append(("Read UINT16 DB1.DBW2", True, f"value={val} (expect 42)"))
            else:
                results.append(("Read UINT16 DB1.DBW2", False, f"value={val} (expect 42), raw={data.hex()}"))
        except Exception as exc:
            results.append(("Read UINT16 DB1.DBW2", False, str(exc)))

        # ---- Test 3: Read FLOAT32 (DB1.DBD4 = temperature, expect 55.5) ----
        try:
            data = client.db_read(1, 4, 4)  # DB1, offset 4, 4 bytes
            val = struct.unpack(">f", data)[0]
            if abs(val - 55.5) < 0.01:
                results.append(("Read FLOAT32 DB1.DBD4", True, f"value={val:.1f} (expect 55.5)"))
            else:
                results.append(("Read FLOAT32 DB1.DBD4", False, f"value={val} (expect 55.5), raw={data.hex()}"))
        except Exception as exc:
            results.append(("Read FLOAT32 DB1.DBD4", False, str(exc)))

        # ---- Test 4: Read FLOAT32 (DB1.DBD8 = speed_setpoint, expect 1500.0) ----
        try:
            data = client.db_read(1, 8, 4)
            val = struct.unpack(">f", data)[0]
            if abs(val - 1500.0) < 0.01:
                results.append(("Read FLOAT32 DB1.DBD8", True, f"value={val:.1f} (expect 1500.0)"))
            else:
                results.append(("Read FLOAT32 DB1.DBD8", False, f"value={val} (expect 1500.0), raw={data.hex()}"))
        except Exception as exc:
            results.append(("Read FLOAT32 DB1.DBD8", False, str(exc)))

        # ---- Test 5: Read FLOAT32 (DB1.DBD12 = actual_speed, expect 1480.0) ----
        try:
            data = client.db_read(1, 12, 4)
            val = struct.unpack(">f", data)[0]
            if abs(val - 1480.0) < 0.01:
                results.append(("Read FLOAT32 DB1.DBD12", True, f"value={val:.1f} (expect 1480.0)"))
            else:
                results.append(("Read FLOAT32 DB1.DBD12", False, f"value={val} (expect 1480.0), raw={data.hex()}"))
        except Exception as exc:
            results.append(("Read FLOAT32 DB1.DBD12", False, str(exc)))

        # ---- Test 6: Write FLOAT32 to DB1.DBD4 (write 99.9) ----
        try:
            write_data = struct.pack(">f", 99.9)
            client.db_write(1, 4, write_data)
            # Read back
            read_data = client.db_read(1, 4, 4)
            val = struct.unpack(">f", read_data)[0]
            if abs(val - 99.9) < 0.01:
                results.append(("Write+Read FLOAT32 DB1.DBD4", True, f"write=99.9, read={val:.1f}"))
            else:
                results.append(("Write+Read FLOAT32 DB1.DBD4", False, f"write=99.9, read={val}, raw={read_data.hex()}"))
        except Exception as exc:
            results.append(("Write+Read FLOAT32 DB1.DBD4", False, str(exc)))

        # ---- Test 7: Write UINT16 to DB1.DBW2 (write 100) ----
        try:
            write_data = struct.pack(">H", 100)
            client.db_write(1, 2, write_data)
            read_data = client.db_read(1, 2, 2)
            val = struct.unpack(">H", read_data)[0]
            if val == 100:
                results.append(("Write+Read UINT16 DB1.DBW2", True, f"write=100, read={val}"))
            else:
                results.append(("Write+Read UINT16 DB1.DBW2", False, f"write=100, read={val}"))
        except Exception as exc:
            results.append(("Write+Read UINT16 DB1.DBW2", False, str(exc)))

        # ---- Test 8: Read full DB1 block (offset 0, 16 bytes) ----
        try:
            data = client.db_read(1, 0, 16)
            results.append(("Read DB1 full block 0-15", True, f"16 bytes: {data.hex()}"))
        except Exception as exc:
            results.append(("Read DB1 full block 0-15", False, str(exc)))

    except Exception as exc:
        results.append(("Connect", False, str(exc)))
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
        try:
            client.destroy()
        except Exception:
            pass

    return results


async def main():
    print("=" * 64)
    print("ProtoForge S7 Protocol Diagnostic Test")
    print("=" * 64)
    print()

    print(f"Starting S7 server on {HOST}:{PORT} ...")
    server = await start_server()
    await asyncio.sleep(0.5)
    print(f"Server started, device created with optimized_db=True")
    print()

    print("Running tests (in separate thread) ...")
    print()
    # Run blocking snap7 tests in a thread, asyncio loop stays alive
    results = await asyncio.to_thread(run_tests)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed

    for name, ok, detail in results:
        status = "[PASS]" if ok else "[FAIL]"
        print(f"  {status} {name}")
        print(f"         {detail}")

    print()
    print("=" * 64)
    print(f"Results: {passed} passed, {failed} failed, {len(results)} total")
    print("=" * 64)

    print("\nStopping server ...")
    await server.stop()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
