#!/usr/bin/env python3
"""Full diagnostic: check services, devices, data collection, protocol reads."""
import socket
import struct
import time

import httpx

PF = "http://127.0.0.1:8000"
EL = "http://127.0.0.1:8180"

client = httpx.Client(timeout=30)

print("=" * 60)
print("1. SERVICE HEALTH CHECK")
print("=" * 60)

# Check ProtoForge
try:
    r = client.get(f"{PF}/health", timeout=10)
    pf_health = r.json()
    print(f"  ProtoForge: {r.status_code} {pf_health.get('status')}")
    protos = pf_health.get("protocols", {}).get("details", {})
    for k in ["modbus_tcp", "s7", "fins", "mc", "mqtt", "http"]:
        p = protos.get(k, {})
        print(f"    {k:15s}: {p.get('status', '?')}")
except Exception as e:
    print(f"  ProtoForge: OFFLINE ({e})")

# Check EdgeLite
try:
    r = client.get(f"{EL}/health", timeout=10)
    print(f"  EdgeLite: {r.status_code} {r.json().get('status', '?')}")
except Exception as e:
    print(f"  EdgeLite: OFFLINE ({e})")

# Check ports
print("\n  Port Check:")
for name, port in [("Modbus", 5020), ("S7", 102), ("FINS", 9600), ("MC", 5000)]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        print(f"    {name:10s} (:{port:5d}): LISTENING")
    except Exception:
        print(f"    {name:10s} (:{port:5d}): NOT LISTENING")

print("\n" + "=" * 60)
print("2. LOGIN & TOKEN")
print("=" * 60)

# Login PF
try:
    r = client.post(f"{PF}/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    d = r.json()
    inner = d.get("data") or d
    pf_token = inner.get("access_token", "")
    pf_headers = {"Authorization": f"Bearer {pf_token}"}
    print(f"  PF login: {r.status_code} (token={'OK' if pf_token else 'FAIL'})")
except Exception as e:
    print(f"  PF login: FAILED ({e})")
    pf_headers = {}

# Login EL
try:
    r = client.post(f"{EL}/api/v1/auth/login", json={"username": "admin", "password": "EdgeLite@2026"})
    d = r.json()
    inner = d.get("data") or d
    el_token = inner.get("access_token", "")
    el_headers = {"Authorization": f"Bearer {el_token}"}
    print(f"  EL login: {r.status_code} (token={'OK' if el_token else 'FAIL'})")
except Exception as e:
    print(f"  EL login: FAILED ({e})")
    el_headers = {}

print("\n" + "=" * 60)
print("3. EDGELITE DEVICES")
print("=" * 60)

try:
    r = client.get(f"{EL}/api/v1/devices", headers=el_headers, params={"limit": 100})
    if r.status_code == 200:
        devices = r.json().get("data", [])
        print(f"  Total devices: {len(devices)}")
        for dev in devices:
            did = dev.get("device_id", "")
            proto = dev.get("protocol", "")
            status = dev.get("status", "")
            pts = dev.get("points", [])
            print(f"\n  {did} ({proto}) Status: {status}")
            for p in pts:
                print(f"    {p.get('name','?')} addr={p.get('address','?')} type={p.get('data_type','?')}")
    else:
        print(f"  GET devices: {r.status_code}")
except Exception as e:
    print(f"  Error: {e}")

print("\n" + "=" * 60)
print("4. REAL-TIME DATA (per device)")
print("=" * 60)

try:
    r = client.get(f"{EL}/api/v1/devices", headers=el_headers, params={"limit": 100})
    if r.status_code == 200:
        for dev in r.json().get("data", []):
            did = dev.get("device_id", "")
            proto = dev.get("protocol", "")
            # Try real-time points
            r2 = client.get(f"{EL}/api/v1/devices/{did}/points", headers=el_headers)
            if r2.status_code == 200:
                data = r2.json().get("data", {})
                if data:
                    print(f"\n  {did} ({proto}):")
                    for pt_name, pt_data in data.items():
                        val = pt_data.get("value", "?")
                        qual = pt_data.get("quality", "?")
                        src = pt_data.get("source", "?")
                        print(f"    {pt_name}: value={val} quality={qual} source={src}")
                else:
                    print(f"\n  {did} ({proto}): NO DATA")
            else:
                print(f"\n  {did} ({proto}): HTTP {r2.status_code}")
except Exception as e:
    print(f"  Error: {e}")

print("\n" + "=" * 60)
print("5. DATA HISTORY QUERY")
print("=" * 60)

# Try time-series query
try:
    r = client.get(f"{EL}/api/v1/data/latest", headers=el_headers, params={"limit": 20})
    print(f"  GET /api/v1/data/latest: {r.status_code}")
    if r.status_code == 200:
        data = r.json().get("data", [])
        print(f"  Records: {len(data) if isinstance(data, list) else 'N/A'}")
        if isinstance(data, list) and data:
            for rec in data[:5]:
                print(f"    {rec}")
except Exception as e:
    print(f"  Error: {e}")

# Try time-series range query
try:
    now_ts = int(time.time())
    r = client.get(f"{EL}/api/v1/data/query", headers=el_headers,
                   params={"start": now_ts - 3600, "end": now_ts, "limit": 20})
    print(f"  GET /api/v1/data/query: {r.status_code}")
    if r.status_code == 200:
        data = r.json().get("data", [])
        print(f"  Records: {len(data) if isinstance(data, list) else 'N/A'}")
except Exception as e:
    print(f"  Error: {e}")

print("\n" + "=" * 60)
print("6. PROTOCOL DIRECT READ TEST")
print("=" * 60)

# Modbus direct read
print("  Modbus TCP:")
try:
    from pymodbus.client import ModbusTcpClient as ModbusClient
    mc = ModbusClient("127.0.0.1", 5020)
    mc.connect()
    rr = mc.read_holding_registers(0, 2, slave=1)
    if rr and not rr.isError():
        print(f"    Holding[0,1]: {rr.registers}")
    else:
        print(f"    Read error: {rr}")
    mc.close()
except Exception as e:
    print(f"    Error: {e}")

# S7 direct read
print("  S7:")
try:
    import snap7
    s7 = snap7.client.Client()
    s7.connect("127.0.0.1", 0, 1)
    data = s7.db_read(1, 0, 4)
    val = struct.unpack(">f", data[:4])[0]
    print(f"    DB1.DBD0: {val}")
    s7.disconnect()
except Exception as e:
    print(f"    Error: {e}")

# FINS direct read
print("  FINS:")
try:
    import sys
    sys.path.insert(0, r"e:\硕腾网络\PyGBSentry\EdgeLite\EdgeLite-v1.0-Community\src")
    from fins.tcp import TCPFinsConnection
    fc = TCPFinsConnection()
    fc.connect("127.0.0.1", 9600)
    val = fc.read("d", 0, data_type="r", number_of_values=1)
    print(f"    DM0: {val}")
    fc.fins_socket.close()
except Exception as e:
    print(f"    Error: {e}")

# MC direct read
print("  MC:")
try:
    from pymcprotocol import Type3E
    mc = Type3E(plctype="iQ-R")
    mc.connect("127.0.0.1", 5000)
    r = mc.batchread_wordunits("D100", 2)
    print(f"    D100: {r}")
    mc.close()
except Exception as e:
    print(f"    Error: {e}")

print("\n" + "=" * 60)
print("7. EDGELITE LOG TAIL")
print("=" * 60)

# Check EdgeLite logs
import os

log_paths = [
    r"e:\硕腾网络\PyGBSentry\ProtoForge\data\logs\edgelite.log",
    r"e:\硕腾网络\PyGBSentry\EdgeLite\EdgeLite-v1.0-Community\data\logs\edgelite.log",
]
for lp in log_paths:
    if os.path.exists(lp) and os.path.getsize(lp) > 0:
        print(f"  Log: {lp} ({os.path.getsize(lp)} bytes)")
        with open(lp, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            for line in lines[-10:]:
                print(f"    {line.rstrip()[:200]}")
        break
else:
    print("  No log file found or empty")

client.close()
print("\n" + "=" * 60)
print("DIAGNOSTIC COMPLETE")
print("=" * 60)
