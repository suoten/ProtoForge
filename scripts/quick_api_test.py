"""Quick API test for 3 key endpoints."""
import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = 'http://localhost:8000/api/v1'

# API 1: Login
print("=== API 1: POST /api/v1/auth/login ===")
r = requests.post(f'{BASE}/auth/login', json={'username': 'admin', 'password': 'admin'})
print(f"Status: {r.status_code}")
data = r.json()
print(f"Keys: {list(data.keys())}")
print(f"Has access_token: {'access_token' in data}")
print(f"Has refresh_token: {'refresh_token' in data}")
print(f"Has username: {data.get('username', 'MISSING')}")
print(f"Has role: {data.get('role', 'MISSING')}")
token = data['access_token']
headers = {'Authorization': f'Bearer {token}'}
print()

# API 2: GET /api/v1/devices
print("=== API 2: GET /api/v1/devices ===")
r = requests.get(f'{BASE}/devices', headers=headers)
print(f"Status: {r.status_code}")
d = r.json()
if isinstance(d, list):
    print(f"Type: list, Count: {len(d)}")
    if d:
        print(f"First device keys: {list(d[0].keys())}")
        print(f"First device: id={d[0].get('id')}, name={d[0].get('name')}, protocol={d[0].get('protocol')}")
elif isinstance(d, dict):
    print(f"Type: dict, Keys: {list(d.keys())}")
    devs = d.get('devices', [])
    print(f"Device count: {len(devs)}")
    if devs:
        print(f"First device: id={devs[0].get('id')}, name={devs[0].get('name')}")
print()

# API 3: GET /api/v1/protocols/info
print("=== API 3: GET /api/v1/protocols/info ===")
r = requests.get(f'{BASE}/protocols/info', headers=headers)
print(f"Status: {r.status_code}")
d = r.json()
if isinstance(d, dict):
    print(f"Type: dict, Keys: {list(d.keys())}")
    protocols = d.get('protocols', [])
    print(f"Protocol count: {len(protocols)}")
    for p in protocols[:3]:
        print(f"  - {p.get('name')}: {p.get('display_name')}, status={p.get('status')}")
elif isinstance(d, list):
    print(f"Type: list, Count: {len(d)}")
    for p in d[:3]:
        print(f"  - {p.get('name')}: {p.get('display_name')}")
