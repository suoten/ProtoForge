#!/usr/bin/env python3
"""Delete existing ProtoForge devices and recreate test devices."""
import httpx
import json
import time

PF = "http://127.0.0.1:8000"
EL = "http://127.0.0.1:8180"

client = httpx.Client(timeout=60)

# Login to ProtoForge
r = client.post(f"{PF}/api/v1/auth/login", json={"username": "admin", "password": "admin"})
d = r.json()
inner = d.get("data") or d
pf_token = inner.get("access_token", "") or inner.get("token", "")
pf_headers = {"Authorization": f"Bearer {pf_token}"}
print(f"PF login: {r.status_code} (token={'OK' if pf_token else 'FAIL'})")

# Login to EdgeLite
r = client.post(f"{EL}/api/v1/auth/login", json={"username": "admin", "password": "EdgeLite@2026"})
d = r.json()
inner = d.get("data") or d
el_token = inner.get("access_token", "")
csrf = inner.get("csrf_token", "")
el_headers = {"Authorization": f"Bearer {el_token}"}
if csrf:
    el_headers["X-CSRF-Token"] = csrf
print(f"EL login: {r.status_code}")

# Delete known devices from ProtoForge
for did in ["test-modbus-001", "test-s7-001", "test-fins-001", "test-mc-001"]:
    r = client.delete(f"{PF}/api/v1/devices/{did}", headers=pf_headers)
    print(f"  PF delete {did}: {r.status_code}")

# Clean ALL devices from EdgeLite
r = client.get(f"{EL}/api/v1/devices", headers=el_headers, params={"limit": 100})
if r.status_code == 200:
    for dev in r.json().get("data", []):
        did = dev.get("device_id", "")
        client.delete(f"{EL}/api/v1/devices/{did}", headers=el_headers)
    print(f"  EL: cleared all devices")

# Create fresh devices
devices = [
    {"id": "test-modbus-001", "name": "Modbus Test", "protocol": "modbus_tcp",
     "protocol_config": {"host": "127.0.0.1", "port": 5020, "slave_id": 1,
         "edgelite_enabled": True, "edgelite_url": "http://127.0.0.1:8180",
         "edgelite_username": "admin", "edgelite_password": "EdgeLite@2026"},
     "points": [{"name": "Voltage", "data_type": "float32", "address": "0", "unit": "V", "access_mode": "rw"},
                {"name": "Current", "data_type": "float32", "address": "2", "unit": "A", "access_mode": "rw"}]},
    {"id": "test-s7-001", "name": "S7 Test", "protocol": "s7",
     "protocol_config": {"host": "127.0.0.1", "port": 102, "rack": 0, "slot": 1,
         "edgelite_enabled": True, "edgelite_url": "http://127.0.0.1:8180",
         "edgelite_username": "admin", "edgelite_password": "EdgeLite@2026"},
     "points": [{"name": "Temperature", "data_type": "float32", "address": "DB1.DBD0", "unit": "C", "access_mode": "rw"}]},
    {"id": "test-fins-001", "name": "FINS Test", "protocol": "fins",
     "protocol_config": {"host": "127.0.0.1", "port": 9600,
         "edgelite_enabled": True, "edgelite_url": "http://127.0.0.1:8180",
         "edgelite_username": "admin", "edgelite_password": "EdgeLite@2026"},
     "points": [{"name": "Temperature", "data_type": "float32", "address": "DM0", "unit": "C", "access_mode": "rw"},
                {"name": "Pressure", "data_type": "float32", "address": "DM2", "unit": "MPa", "access_mode": "rw"}]},
    {"id": "test-mc-001", "name": "MC Test", "protocol": "mc",
     "protocol_config": {"host": "127.0.0.1", "port": 5000,
         "edgelite_enabled": True, "edgelite_url": "http://127.0.0.1:8180",
         "edgelite_username": "admin", "edgelite_password": "EdgeLite@2026"},
     "points": [{"name": "Temperature", "data_type": "float32", "address": "D100", "unit": "C", "access_mode": "rw"}]},
]

print("\n=== Creating devices ===")
for dev in devices:
    r = client.post(f"{PF}/api/v1/devices", headers=pf_headers, json=dev)
    print(f"  {dev['id']}: {r.status_code}")
    if r.status_code not in (200, 201):
        print(f"    Error: {r.text[:200]}")

# Wait for push
print("\nWaiting 10s for auto-push...")
time.sleep(10)

# Check EdgeLite devices
print("\n=== EdgeLite Devices ===")
r = client.get(f"{EL}/api/v1/devices", headers=el_headers, params={"limit": 50})
if r.status_code == 200:
    for dev in r.json().get("data", []):
        did = dev.get("device_id", "")
        proto = dev.get("protocol", "")
        status = dev.get("status", "")
        pts = dev.get("points", [])
        print(f"\n  {did} ({proto}) Status: {status}")
        for p in pts:
            print(f"    {p.get('name','?')} addr={p.get('address','?')} type={p.get('data_type','?')}")

# Wait for data collection
print("\nWaiting 20s for data collection...")
time.sleep(20)

# Check real-time data
print("\n=== Real-time Data ===")
r = client.get(f"{EL}/api/v1/devices", headers=el_headers, params={"limit": 50})
if r.status_code == 200:
    for dev in r.json().get("data", []):
        did = dev.get("device_id", "")
        r2 = client.get(f"{EL}/api/v1/devices/{did}/points", headers=el_headers)
        if r2.status_code == 200:
            data = r2.json().get("data", {})
            print(f"\n  {did}:")
            for pt_name, pt_data in data.items():
                val = pt_data.get("value", "?")
                qual = pt_data.get("quality", "?")
                src = pt_data.get("source", "?")
                print(f"    {pt_name}: value={val} quality={qual} source={src}")

client.close()
print("\nDone!")
