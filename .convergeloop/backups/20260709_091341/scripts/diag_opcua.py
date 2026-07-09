"""
Diagnostic test script for ProtoForge OPC UA server.

Tests the OPC UA server using the asyncua client library:
  1. Start the ProtoForge OPC UA server with a test device
  2. Connect to the server via asyncua Client
  3. Browse the node tree and find the test device folder
  4. Read a float32 point value (temperature=25.0)
  5. Write a new value (42.5) to the temperature point
  6. Read back and verify the value
  7. Read an int32 point value
  8. Write a new value and read back

Usage:
    python scripts/diag_opcua.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import traceback

from protoforge.protocols.opcua.server import OpcUaServer
from protoforge.models.device import DeviceConfig, PointConfig

# ---------------------------------------------------------------------------
# Test counters
# ---------------------------------------------------------------------------
_passed = 0
_failed = 0


def _result(name: str, ok: bool, detail: str = ""):
    global _passed, _failed
    tag = "PASS" if ok else "FAIL"
    if ok:
        _passed += 1
    else:
        _failed += 1
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{tag}] {name}{suffix}")


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------
async def start_server() -> OpcUaServer:
    server = OpcUaServer()
    config = DeviceConfig(
        id="test-opcua",
        name="Test OPCUA Device",
        protocol="opcua",
        points=[
            PointConfig(
                name="temperature",
                address="temperature",
                data_type="float32",
                access="rw",
                fixed_value=25.0,
            ),
            PointConfig(
                name="pressure",
                address="pressure",
                data_type="int32",
                access="rw",
                fixed_value=100,
            ),
            PointConfig(
                name="status",
                address="status",
                data_type="bool",
                access="rw",
                fixed_value=True,
            ),
        ],
    )
    await server.create_device(config)
    await server.start({"host": "127.0.0.1", "port": 4840})
    # Give the server a moment to be ready
    await asyncio.sleep(1)
    return server


# ---------------------------------------------------------------------------
# Client tests
# ---------------------------------------------------------------------------
async def run_tests():
    from asyncua import Client

    server = None
    try:
        # ---- Start server ----
        print("\n=== Starting ProtoForge OPC UA Server ===")
        server = await start_server()
        _result("Server started", server.status.value == "running")

        # ---- Connect ----
        print("\n=== Test 1: Connect to server ===")
        client = Client("opc.tcp://127.0.0.1:4840/protoforge")
        await client.connect()
        _result("Client connected", True)

        try:
            # ---- Browse node tree ----
            print("\n=== Test 2: Browse node tree ===")
            objects = client.nodes.objects
            children = await objects.get_children()
            _result("Objects folder has children", len(children) > 0,
                    f"children count: {len(children)}")

            # Find the device folder by browsing display names
            device_folder = None
            for child in children:
                browse_name = await child.read_browse_name()
                if browse_name.Name == "Test OPCUA Device":
                    device_folder = child
                    break
            _result("Found device folder 'Test OPCUA Device'", device_folder is not None)

            # Get point nodes inside the device folder
            point_nodes = {}
            if device_folder is not None:
                device_children = await device_folder.get_children()
                for dc in device_children:
                    bn = await dc.read_browse_name()
                    point_nodes[bn.Name] = dc
            _result("Device folder has point nodes", len(point_nodes) > 0,
                    f"points: {list(point_nodes.keys())}")

            # ---- Read float32 temperature (initial=25.0) ----
            print("\n=== Test 3: Read float32 point (temperature) ===")
            temp_node = point_nodes.get("temperature")
            if temp_node is not None:
                temp_val = await temp_node.read_value()
                # asyncua may return float; allow small rounding
                temp_ok = isinstance(temp_val, (int, float)) and abs(temp_val - 25.0) < 0.01
                _result("Read temperature value", temp_ok,
                        f"got={temp_val}, expected=25.0")
            else:
                _result("Read temperature value", False, "node not found")

            # ---- Write 42.5 to temperature ----
            print("\n=== Test 4: Write float32 point (temperature=42.5) ===")
            if temp_node is not None:
                try:
                    await temp_node.write_value(42.5)
                    _result("Write temperature=42.5", True)
                except Exception as e:
                    _result("Write temperature=42.5", False, str(e))
            else:
                _result("Write temperature=42.5", False, "node not found")

            # ---- Read back temperature and verify ----
            print("\n=== Test 5: Read back temperature and verify ===")
            if temp_node is not None:
                temp_val2 = await temp_node.read_value()
                verify_ok = isinstance(temp_val2, (int, float)) and abs(temp_val2 - 42.5) < 0.01
                _result("Temperature read-back matches 42.5", verify_ok,
                        f"got={temp_val2}")
            else:
                _result("Temperature read-back matches 42.5", False, "node not found")

            # ---- Read int32 pressure (initial=100) ----
            print("\n=== Test 6: Read int32 point (pressure) ===")
            press_node = point_nodes.get("pressure")
            if press_node is not None:
                press_val = await press_node.read_value()
                press_ok = isinstance(press_val, (int, float)) and press_val == 100
                _result("Read pressure value", press_ok,
                        f"got={press_val}, expected=100")
            else:
                _result("Read pressure value", False, "node not found")

            # ---- Write 200 to pressure and read back ----
            print("\n=== Test 7: Write int32 point (pressure=200) and read back ===")
            if press_node is not None:
                try:
                    await press_node.write_value(200)
                    _result("Write pressure=200", True)
                except Exception as e:
                    _result("Write pressure=200", False, str(e))

                press_val2 = await press_node.read_value()
                press_verify = isinstance(press_val2, (int, float)) and press_val2 == 200
                _result("Pressure read-back matches 200", press_verify,
                        f"got={press_val2}")
            else:
                _result("Write pressure=200", False, "node not found")
                _result("Pressure read-back matches 200", False, "node not found")

        finally:
            await client.disconnect()
            _result("Client disconnected", True)

    except Exception as e:
        _result("Unexpected error", False, str(e))
        traceback.print_exc()
    finally:
        if server is not None:
            print("\n=== Stopping server ===")
            await server.stop()
            _result("Server stopped", True)

    # ---- Summary ----
    total = _passed + _failed
    print(f"\n{'='*50}")
    print(f"Results: {_passed}/{total} passed, {_failed}/{total} failed")
    if _failed == 0:
        print("All tests PASSED!")
    else:
        print("Some tests FAILED.")
    return _failed == 0


if __name__ == "__main__":
    ok = asyncio.run(run_tests())
    sys.exit(0 if ok else 1)
