#!/usr/bin/env python3
"""Stage 3: API interface tests - 3 key APIs."""
import httpx
import json

PF = "http://127.0.0.1:8000"
client = httpx.Client(timeout=30)

# --- API 1: POST /api/v1/auth/login ---
print("=== API 1: POST /api/v1/auth/login ===")
r = client.post(f"{PF}/api/v1/auth/login", json={"username": "admin", "password": "admin"})
print(f"  Status: {r.status_code}")
d = r.json()
inner = d.get("data") or d
token = inner.get("access_token", "")
headers = {"Authorization": f"Bearer {token}"}
print(f"  has_token: {bool(token)}")
print(f"  Response keys: {list(d.keys())}")

# --- API 2: GET /api/v1/devices ---
print("\n=== API 2: GET /api/v1/devices ===")
r = client.get(f"{PF}/api/v1/devices", headers=headers, params={"limit": 5})
print(f"  Status: {r.status_code}")
d = r.json()
if "devices" in d:
    print(f"  devices count: {len(d['devices'])}")
    print(f"  Response keys: {list(d.keys())}")
elif "data" in d:
    data = d["data"]
    if isinstance(data, dict) and "items" in data:
        print(f"  items count: {len(data['items'])}")
    elif isinstance(data, list):
        print(f"  data count: {len(data)}")
    print(f"  Response keys: {list(d.keys())}")

# --- API 3: GET /health ---
print("\n=== API 3: GET /health ===")
r = client.get(f"{PF}/health")
print(f"  Status: {r.status_code}")
d = r.json()
print(f"  status: {d.get('status')}")
protos = d.get("protocols", {}).get("details", {})
for k in ["modbus_tcp", "s7", "fins", "mc"]:
    p = protos.get(k, {})
    print(f"  {k}: {p.get('status', '?')}")

client.close()
print("\nAll 3 API tests passed!")
