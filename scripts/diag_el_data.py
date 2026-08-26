#!/usr/bin/env python3
"""Diagnose EdgeLite data collection: check device points, driver status, and data."""
import httpx
import json
import time

EL = "http://127.0.0.1:8180"
EL_USER = "admin"
EL_PASS = "EdgeLite@2026"

client = httpx.Client(timeout=60)

# Login
r = client.post(f"{EL}/api/v1/auth/login", json={"username": EL_USER, "password": EL_PASS})
d = r.json()
inner = d.get("data") or d
token = inner.get("access_token", "")
csrf = inner.get("csrf_token", "")
headers = {"Authorization": f"Bearer {token}"}
if csrf:
    headers["X-CSRF-Token"] = csrf
print(f"EL login: {r.status_code}")

# 1. List all devices with full details
print("\n=== EdgeLite Devices ===")
r = client.get(f"{EL}/api/v1/devices", headers=headers, params={"limit": 50})
if r.status_code == 200:
    devices = r.json().get("data", [])
    print(f"Total devices: {len(devices)}")
    for dev in devices:
        did = dev.get("device_id", "")
        proto = dev.get("protocol", "")
        status = dev.get("status", "")
        cfg = dev.get("config", {})
        points = dev.get("points", [])
        print(f"\n  Device: {did}")
        print(f"    Protocol: {proto}, Status: {status}")
        print(f"    Config: {json.dumps(cfg, ensure_ascii=False)[:200]}")
        print(f"    Points ({len(points)}):")
        for p in points[:5]:
            print(f"      - name={p.get('name','?')} address={p.get('address','?')} "
                  f"type={p.get('data_type','?')} unit={p.get('unit','')}")

# 2. Try to read real-time data
print("\n=== Real-time Data ===")
for dev in devices:
    did = dev.get("device_id", "")
    # Try different data endpoints
    for endpoint in [f"/api/v1/devices/{did}/data", f"/api/v1/data/{did}", f"/api/v1/devices/{did}/points"]:
        r = client.get(f"{EL}{endpoint}", headers=headers)
        if r.status_code == 200:
            data = r.json()
            print(f"  {did} ({endpoint}): {json.dumps(data, ensure_ascii=False)[:300]}")
            break
    else:
        print(f"  {did}: no data endpoint returned 200")

# 3. Try data query API
print("\n=== Data Query ===")
r = client.get(f"{EL}/api/v1/data", headers=headers, params={"limit": 10})
print(f"  /api/v1/data: {r.status_code} {r.text[:200]}")

# 4. Check device detail with points
print("\n=== Device Detail ===")
for dev in devices[:2]:
    did = dev.get("device_id", "")
    r = client.get(f"{EL}/api/v1/devices/{did}", headers=headers)
    if r.status_code == 200:
        detail = r.json().get("data", r.json())
        print(f"  {did}:")
        print(f"    status: {detail.get('status')}")
        print(f"    error: {detail.get('error_message', '')}")
        print(f"    last_read: {detail.get('last_read_at', '')}")
        pts = detail.get("points", [])
        for p in pts[:3]:
            print(f"    point: {p.get('name','?')} value={p.get('value','?')} "
                  f"quality={p.get('quality','?')} last_updated={p.get('last_updated','?')}")

client.close()
print("\nDone!")
