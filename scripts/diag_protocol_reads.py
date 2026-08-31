#!/usr/bin/env python3
"""Check ProtoForge protocol server status and test direct reads."""
import socket
import struct

import httpx

PF = "http://127.0.0.1:8000"

client = httpx.Client(timeout=30)

# Check health
r = client.get(f"{PF}/health")
d = r.json()
protos = d.get("protocols", {}).get("details", {})
print("=== Protocol Server Status ===")
for k in ["modbus_tcp", "s7", "fins", "mc", "mqtt", "http"]:
    p = protos.get(k, {})
    print(f"  {k:15s}: {p.get('status', '?')}")

# Check if ports are listening
print("\n=== Port Check ===")
for name, port in [("Modbus", 5020), ("S7", 102), ("FINS", 9600), ("MC", 5000), ("MQTT", 1883), ("HTTP", 8080)]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        print(f"  {name:10s} (:{port:5d}): LISTENING")
    except Exception:
        print(f"  {name:10s} (:{port:5d}): NOT LISTENING")

# Test FINS read directly using fins library
print("\n=== Direct FINS Read Test ===")
try:
    import sys
    sys.path.insert(0, r"e:\硕腾网络\PyGBSentry\EdgeLite\EdgeLite-v1.0-Community\src")
    from fins.tcp import TCPFinsConnection

    fins_conn = TCPFinsConnection()
    fins_conn.connect("127.0.0.1", 9600)
    print(f"  FINS connected: {fins_conn.fins_socket is not None}")

    # Try reading DM0 (area code 0x82, word address 0)
    result = fins_conn.read("d", 0, data_type="r", number_of_values=1)
    print(f"  DM0 read result: {result}")

    # Try reading DM2
    result2 = fins_conn.read("d", 2, data_type="r", number_of_values=1)
    print(f"  DM2 read result: {result2}")

    fins_conn.fins_socket.close()
except Exception as e:
    print(f"  FINS read error: {e}")

# Test S7 read directly using snap7
print("\n=== Direct S7 Read Test ===")
try:
    from snap7 import Client as S7Client

    s7 = S7Client()
    s7.connect("127.0.0.1", 0, 1)
    print(f"  S7 connected: {s7.get_connected()}")

    # Try reading DB1.DBD0 (4 bytes = float32)
    data = s7.db_get(1, 0, 4)
    print(f"  DB1.DBD0 raw: {data.hex()}")
    if len(data) >= 4:
        val = struct.unpack(">f", data[:4])[0]
        print(f"  DB1.DBD0 value: {val}")

    s7.disconnect()
except Exception as e:
    print(f"  S7 read error: {e}")

# Test MC read directly
print("\n=== Direct MC Read Test ===")
try:
    from pymcprotocol import mc3e

    mc = mc3e()
    mc.connect("127.0.0.1", 5000)
    print("  MC connected")

    # Try reading D100
    result = mc.batch_read_word_units(head_device="D100", size=2)
    print(f"  D100 read result: {result}")

    mc.disconnect()
except Exception as e:
    print(f"  MC read error: {e}")

client.close()
print("\nDone!")
