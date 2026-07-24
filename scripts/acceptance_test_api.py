"""Automated acceptance test script for ProtoForge API endpoints."""
import requests
import json
import sys

BASE = 'http://localhost:8000/api/v1'

def main():
    # Login
    r = requests.post(f'{BASE}/auth/login', json={'username': 'admin', 'password': 'admin'})
    token = r.json().get('access_token', '')
    headers = {'Authorization': f'Bearer {token}'}
    print(f'Login: {r.status_code}')

    endpoints = [
        ('GET', '/health', 'Health'),
        ('GET', '/protocols', 'Protocols List'),
        ('GET', '/protocols/info', 'Protocols Info'),
        ('GET', '/devices', 'Devices List'),
        ('GET', '/templates', 'Templates List'),
        ('GET', '/templates/tags', 'Template Tags'),
        ('GET', '/scenarios', 'Scenarios List'),
        ('GET', '/logs', 'Logs'),
        ('GET', '/settings', 'Settings'),
        ('GET', '/audit', 'Audit Log'),
        ('GET', '/audit/stats', 'Audit Stats'),
        ('GET', '/forward/targets', 'Forward Targets'),
        ('GET', '/forward/stats', 'Forward Stats'),
        ('GET', '/recorder/recordings', 'Recorder Recordings'),
        ('GET', '/recorder/stats', 'Recorder Stats'),
        ('GET', '/webhooks', 'Webhooks'),
        ('GET', '/webhooks/stats', 'Webhook Stats'),
        ('GET', '/integration/status', 'Integration Status'),
        ('GET', '/integration/metrics', 'Integration Metrics'),
        ('GET', '/integration/protocols', 'Integration Protocols'),
        ('GET', '/integration/device-status', 'Integration Device Status'),
        ('GET', '/integration/alarm-rules', 'Integration Alarm Rules'),
        ('GET', '/tests/cases', 'Test Cases'),
        ('GET', '/tests/suites', 'Test Suites'),
        ('GET', '/tests/reports', 'Test Reports'),
        ('GET', '/tests/suggestions', 'Test Suggestions'),
        ('GET', '/tests/action-types', 'Test Action Types'),
        ('GET', '/tests/assertion-types', 'Test Assertion Types'),
        ('GET', '/setup/status', 'Setup Status'),
        ('GET', '/auth/users', 'Users List'),
    ]

    results = []
    for method, path, name in endpoints:
        try:
            if method == 'GET':
                r = requests.get(f'{BASE}{path}', headers=headers, timeout=10)
            else:
                r = requests.post(f'{BASE}{path}', headers=headers, timeout=10)
            status = r.status_code
            data_preview = str(r.text)[:200] if status != 200 else 'OK'
            results.append((name, status, data_preview))
            if status != 200:
                print(f'FAIL [{status}] {name}: {data_preview}')
            else:
                print(f'OK   [{status}] {name}')
        except Exception as e:
            results.append((name, 'ERR', str(e)[:200]))
            print(f'ERR  {name}: {e}')

    ok_count = sum(1 for _, s, _ in results if s == 200)
    fail_count = sum(1 for _, s, _ in results if s != 200)
    print(f'\nTotal: {len(results)}, OK: {ok_count}, FAIL: {fail_count}')
    
    # Also test some specific device operations
    print('\n--- Device Operations ---')
    r = requests.get(f'{BASE}/devices', headers=headers, timeout=10)
    devices = r.json() if r.status_code == 200 else []
    if isinstance(devices, list) and len(devices) > 0:
        device_id = devices[0].get('id', '')
        print(f'First device: {device_id}')
        
        # Test get device detail
        r = requests.get(f'{BASE}/devices/{device_id}', headers=headers, timeout=10)
        print(f'Get device: {r.status_code}')
        
        # Test get device points
        r = requests.get(f'{BASE}/devices/{device_id}/points', headers=headers, timeout=10)
        print(f'Get device points: {r.status_code}')
        
        # Test get device config
        r = requests.get(f'{BASE}/devices/{device_id}/config', headers=headers, timeout=10)
        print(f'Get device config: {r.status_code}')
        
        # Test get device connection guide
        r = requests.get(f'{BASE}/devices/{device_id}/connection-guide', headers=headers, timeout=10)
        print(f'Get connection guide: {r.status_code}')

    # Test protocol config
    print('\n--- Protocol Operations ---')
    r = requests.get(f'{BASE}/protocols/modbus_tcp/config', headers=headers, timeout=10)
    print(f'Modbus TCP config: {r.status_code}')
    
    r = requests.get(f'{BASE}/protocols/modbus_tcp/device-config', headers=headers, timeout=10)
    print(f'Modbus TCP device config: {r.status_code}')

if __name__ == '__main__':
    main()
