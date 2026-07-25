"""Quick pipeline test for smoke detector."""
import requests, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = 'http://localhost:8000/api/v1'
DEVICE_ID = 'test-smoke-pipeline'

# Login
r = requests.post(f'{BASE}/auth/login', json={'username': 'admin', 'password': 'admin'})
token = r.json()['access_token']
headers = {'Authorization': f'Bearer {token}'}

# Wait for EdgeLite to collect
print('Waiting 8s for EdgeLite to collect...')
time.sleep(8)

# Verify pipeline
r = requests.get(f'{BASE}/edgelite/pipeline/{DEVICE_ID}?auto_fix=true', headers=headers, timeout=120)
print(f'Status: {r.status_code}')
result = r.json()

steps = result.get('steps', {})
for s in ['auth', 'register', 'connect', 'collect']:
    step = steps.get(s, {})
    print(f'  {s}: ok={step.get("ok")}')

comp = result.get('data_comparison', [])
if comp:
    print()
    print(f'{"Point":<20} {"PF":>14} {"EL":>14} {"Match":>6}')
    print('-' * 58)
    matched = 0
    for c in comp:
        pf = str(c.get('protoforge_value', ''))[:14]
        el = str(c.get('edgelite_value', ''))[:14]
        m = 'YES' if c.get('match') else 'NO'
        if c.get('match'):
            matched += 1
        print(f'{c["point"]:<20} {pf:>14} {el:>14} {m:>6}')
    print(f'\nMatched: {matched}/{len(comp)}')
else:
    print('No data comparison available')
