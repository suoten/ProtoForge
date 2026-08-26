#!/usr/bin/env python3
"""Diagnose push issues - check devices, integration status, and try push."""
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
el_headers = {"Authorization": f"Bearer {el_token}"}
print(f"EL login: {r.status_code}")

# Check PF devices
print("\n=== ProtoForge Devices ===")
r = client.get(f"{PF}/api/v1/devices", headers=pf_headers, params={"limit": 50})
print(f"  GET /api/v1/devices: {r.status_code}")
if r.status_code == 200:
    d = r.json()
    # Try different response formats
    if isinstance(d.get("data"), dict):
        items = d["data"].get("items", [])
    elif isinstance(d.get("data"), list):
        items = d["data"]
    else:
        items = d.get("items", [])
    print(f"  Devices: {len(items)}")
    for dev in items:
        print(f"    {dev.get('id','?')}: {dev.get('name','?')} ({dev.get('protocol','?')})")
        cfg = dev.get("protocol_config", {})
        print(f"      edgelite_enabled: {cfg.get('edgelite_enabled', 'NOT SET')}")
        print(f"      edgelite_url: {cfg.get('edgelite_url', 'NOT SET')}")

# Check integration status
print("\n=== Integration Status ===")
for endpoint in ["/api/v1/edgelite/status", "/api/v1/integration/status"]:
    r = client.get(f"{PF}{endpoint}", headers=pf_headers)
    print(f"  {endpoint}: {r.status_code} {r.text[:200]}")

# Try to push device
print("\n=== Try Push ===")
for did in ["test-fins-001", "test-modbus-001"]:
    for endpoint in [f"/api/v1/edgelite/push", f"/api/v1/integration/push"]:
        r = client.post(f"{PF}{endpoint}", headers=pf_headers, json={"device_id": did})
        print(f"  POST {endpoint} ({did}): {r.status_code} {r.text[:200]}")
        if r.status_code == 200:
            break

# Wait and check EdgeLite
time.sleep(5)
print("\n=== EdgeLite Devices ===")
r = client.get(f"{EL}/api/v1/devices", headers=el_headers, params={"limit": 50})
if r.status_code == 200:
    devices = r.json().get("data", [])
    print(f"  Total: {len(devices)}")
    for dev in devices:
        print(f"  {dev.get('device_id','?')} ({dev.get('protocol','?')}) Status: {dev.get('status','?')}")

client.close()
