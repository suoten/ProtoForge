"""阶段3接口测试：3个关键API"""
import sys
import io
import json
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE = "http://localhost:8000"

# 登录获取 token
r = requests.post(f"{BASE}/api/v1/auth/login", json={"username": "admin", "password": "admin"})
token = r.json().get("access_token")
H = {"Authorization": f"Bearer {token}"}

print("=== API 1: POST /api/v1/auth/login ===")
print(f"命令: curl -X POST {BASE}/api/v1/auth/login -H 'Content-Type: application/json' -d '{{\"username\":\"admin\",\"password\":\"admin\"}}'")
print(f"返回: status={r.status_code}, access_token={'[存在]' if token else '[缺失]'}, role={r.json().get('role','?')}")
print(f"结果: {'✅ 符合预期' if r.status_code == 200 and token else '❌ 异常'}")
print()

print("=== API 2: GET /api/v1/devices ===")
r2 = requests.get(f"{BASE}/api/v1/devices", headers=H)
resp2 = r2.json()
dev_count = len(resp2.get("devices", []))
print(f"命令: curl {BASE}/api/v1/devices -H 'Authorization: Bearer <token>'")
print(f"返回: status={r2.status_code}, devices_count={dev_count}")
print(f"结果: {'✅ 符合预期' if r2.status_code == 200 and 'devices' in resp2 else '❌ 异常'}")
print()

print("=== API 3: GET /api/v1/templates ===")
r3 = requests.get(f"{BASE}/api/v1/templates", headers=H)
resp3 = r3.json()
if isinstance(resp3, list):
    tmpl_count = len(resp3)
elif isinstance(resp3, dict):
    tmpl_count = len(resp3.get("templates", resp3.get("data", [])))
else:
    tmpl_count = 0
print(f"命令: curl {BASE}/api/v1/templates -H 'Authorization: Bearer <token>'")
print(f"返回: status={r3.status_code}, templates_count={tmpl_count}")
print(f"结果: {'✅ 符合预期' if r3.status_code == 200 and tmpl_count > 0 else '❌ 异常'}")
