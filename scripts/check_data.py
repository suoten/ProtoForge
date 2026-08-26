#!/usr/bin/env python3
"""Quick check S7 and MC data after S7 reconnect fix."""
import httpx
import json
import time

EL = "http://127.0.0.1:8180"
client = httpx.Client(timeout=30)

r = client.post(f"{EL}/api/v1/auth/login", json={"username": "admin", "password": "EdgeLite@2026"})
d = r.json()
inner = d.get("data") or d
token = inner.get("access_token", "")
headers = {"Authorization": f"Bearer {token}"}
print(f"EL login: {r.status_code}")

# Wait extra for data collection
print("Waiting 15s for data collection...")
time.sleep(15)

for did in ["s7-final-test", "mc-final-test"]:
    r2 = client.get(f"{EL}/api/v1/devices/{did}/points", headers=headers)
    if r2.status_code == 200:
        data = r2.json().get("data", {})
        print(f"\n{did}:")
        for pt_name, pt_data in data.items():
            val = pt_data.get("value", "?")
            qual = pt_data.get("quality", "?")
            src = pt_data.get("source", "?")
            print(f"  {pt_name}: value={val} quality={qual} source={src}")

client.close()
