"""Test upload/download and additional edge cases."""
import sys
import io
import os
import time
import json
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright

BASE_URL = 'http://localhost:5173'
API_URL = 'http://localhost:8000/api/v1'

results = []

def add_result(page, status, details='', errors=None, warnings=None):
    r = {'page': page, 'status': status, 'details': details, 'errors': errors or [], 'warnings': warnings or []}
    results.append(r)
    icon = {'PASS': '[OK]', 'WARN': '[WARN]', 'FAIL': '[FAIL]'}[status]
    print(f"{icon} {page} - {details}")
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
    if warnings:
        for w in warnings:
            print(f"  WARN: {w}")
    return r

def login(page):
    page.goto(f'{BASE_URL}/', wait_until='networkidle', timeout=15000)
    page.wait_for_timeout(1000)
    if page.query_selector('.app-layout'):
        return True
    username = page.query_selector('input[placeholder*="用户名"]')
    password = page.query_selector('input[placeholder*="密码"]')
    if username and password:
        username.fill('admin')
        password.fill('admin')
        btn = page.query_selector('button:has-text("登")')
        if btn:
            btn.click()
        page.wait_for_timeout(3000)
        return page.query_selector('.app-layout') is not None
    return False

def test_backup_export_api():
    """Test backup export via API."""
    errors = []
    details = []
    
    try:
        r = requests.post(f'{API_URL}/auth/login', json={'username': 'admin', 'password': 'admin'})
        token = r.json().get('access_token', '')
        headers = {'Authorization': f'Bearer {token}'}
        
        # Test backup export
        r = requests.get(f'{API_URL}/backup', headers=headers, timeout=30, stream=True)
        if r.status_code == 200:
            content_type = r.headers.get('content-type', '')
            content_disposition = r.headers.get('content-disposition', '')
            details.append(f'Backup export: {r.status_code}, type={content_type}')
            details.append(f'Content-Disposition: {content_disposition}')
            
            # Check content is valid JSON
            content = r.content
            try:
                data = json.loads(content)
                details.append(f'Backup content valid JSON, keys: {list(data.keys())[:5]}')
            except:
                details.append(f'Backup content size: {len(content)} bytes')
        else:
            errors.append(f'Backup export failed: {r.status_code}')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Backup Export API', status, '; '.join(details), errors)

def test_scenario_export_import_api():
    """Test scenario export/import via API."""
    errors = []
    details = []
    
    try:
        r = requests.post(f'{API_URL}/auth/login', json={'username': 'admin', 'password': 'admin'})
        token = r.json().get('access_token', '')
        headers = {'Authorization': f'Bearer {token}'}
        
        # Get scenarios
        r = requests.get(f'{API_URL}/scenarios', headers=headers, timeout=10)
        scenarios = r.json() if r.status_code == 200 else []
        if isinstance(scenarios, dict):
            scenarios = scenarios.get('scenarios', [])
        
        if scenarios:
            scenario_id = scenarios[0].get('id', '')
            details.append(f'First scenario: {scenario_id}')
            
            # Test export
            r = requests.get(f'{API_URL}/scenarios/{scenario_id}/export', headers=headers, timeout=10)
            if r.status_code == 200:
                details.append(f'Scenario export: {r.status_code}')
                export_data = r.json() if r.headers.get('content-type', '').startswith('application/json') else None
                if export_data:
                    details.append(f'Export data keys: {list(export_data.keys())[:5]}')
            else:
                errors.append(f'Scenario export failed: {r.status_code}')
        else:
            details.append('No scenarios to test export')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Scenario Export API', status, '; '.join(details), errors)

def test_recorder_export_api():
    """Test recording export via API."""
    errors = []
    details = []
    
    try:
        r = requests.post(f'{API_URL}/auth/login', json={'username': 'admin', 'password': 'admin'})
        token = r.json().get('access_token', '')
        headers = {'Authorization': f'Bearer {token}'}
        
        # Get recordings
        r = requests.get(f'{API_URL}/recorder/recordings', headers=headers, timeout=10)
        recordings = r.json() if r.status_code == 200 else []
        if isinstance(recordings, dict):
            recordings = recordings.get('recordings', [])
        
        details.append(f'Recordings: {len(recordings)}')
        
        if recordings:
            rec_id = recordings[0].get('id', '')
            r = requests.get(f'{API_URL}/recorder/recordings/{rec_id}/export', headers=headers, timeout=10)
            details.append(f'Recording export: {r.status_code}')
        else:
            details.append('No recordings to test export')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Recorder Export API', status, '; '.join(details), errors)

def test_test_report_html_api():
    """Test test report HTML export."""
    errors = []
    details = []
    
    try:
        r = requests.post(f'{API_URL}/auth/login', json={'username': 'admin', 'password': 'admin'})
        token = r.json().get('access_token', '')
        headers = {'Authorization': f'Bearer {token}'}
        
        # Get test reports
        r = requests.get(f'{API_URL}/tests/reports', headers=headers, timeout=10)
        reports = r.json() if r.status_code == 200 else []
        if isinstance(reports, dict):
            reports = reports.get('reports', [])
        
        details.append(f'Test reports: {len(reports)}')
        
        if reports:
            report_id = reports[0].get('id', '')
            # Get HTML report
            r = requests.get(f'{API_URL}/tests/reports/{report_id}/html', headers=headers, timeout=10)
            if r.status_code == 200:
                content = r.text
                if '<html' in content.lower() or '<div' in content.lower():
                    details.append(f'Report HTML valid, size: {len(content)}')
                else:
                    details.append(f'Report HTML content: {content[:100]}')
            else:
                errors.append(f'Report HTML failed: {r.status_code}')
        else:
            details.append('No test reports to test')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Test Report HTML API', status, '; '.join(details), errors)

def test_role_based_access():
    """Test role-based access control."""
    errors = []
    details = []
    
    try:
        r = requests.post(f'{API_URL}/auth/login', json={'username': 'admin', 'password': 'admin'})
        token = r.json().get('access_token', '')
        headers = {'Authorization': f'Bearer {token}'}
        
        # Get user role
        r = requests.get(f'{API_URL}/auth/me', headers=headers, timeout=10)
        if r.status_code == 200:
            user_data = r.json()
            role = user_data.get('role', '')
            details.append(f'Admin role: {role}')
        
        # Test register a new user
        r = requests.post(f'{API_URL}/auth/register', json={
            'username': 'test_viewer',
            'password': 'test123456'
        }, timeout=10)
        if r.status_code == 200:
            details.append('New user registered')
        elif r.status_code == 409:
            details.append('User already exists (expected)')
        else:
            details.append(f'Register returned: {r.status_code}')
        
        # Login as viewer
        r = requests.post(f'{API_URL}/auth/login', json={
            'username': 'test_viewer',
            'password': 'test123456'
        }, timeout=10)
        if r.status_code == 200:
            viewer_token = r.json().get('access_token', '')
            viewer_headers = {'Authorization': f'Bearer {viewer_token}'}
            
            # Viewer should not access settings
            r = requests.get(f'{API_URL}/settings', headers=viewer_headers, timeout=10)
            if r.status_code == 403:
                details.append('Viewer denied settings access (403)')
            else:
                details.append(f'Viewer settings access: {r.status_code}')
            
            # Viewer should not access audit
            r = requests.get(f'{API_URL}/audit', headers=viewer_headers, timeout=10)
            if r.status_code == 403:
                details.append('Viewer denied audit access (403)')
            else:
                details.append(f'Viewer audit access: {r.status_code}')
            
            # Viewer should not access backup
            r = requests.get(f'{API_URL}/backup', headers=viewer_headers, timeout=10)
            if r.status_code == 403:
                details.append('Viewer denied backup access (403)')
            else:
                details.append(f'Viewer backup access: {r.status_code}')
            
            # Viewer should access devices
            r = requests.get(f'{API_URL}/devices', headers=viewer_headers, timeout=10)
            if r.status_code == 200:
                details.append('Viewer can access devices')
            else:
                errors.append(f'Viewer denied devices access: {r.status_code}')
        else:
            details.append(f'Viewer login failed: {r.status_code}')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Role-Based Access', status, '; '.join(details), errors)

def test_integration_page_buttons(page):
    """Test integration page buttons."""
    errors = []
    details = []
    
    try:
        login(page)
        page.goto(f'{BASE_URL}/integration', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        
        # Check for integration status
        body = page.inner_text('body')
        if '联调' in body or '集成' in body or 'integration' in body.lower():
            details.append('Integration page content correct')
        
        # Check for buttons
        buttons = page.query_selector_all('button')
        details.append(f'Buttons: {len(buttons)}')
        
        # Check for connect/test button
        test_btn = page.query_selector('button:has-text("测试"), button:has-text("连接"), button:has-text("Test")')
        if test_btn:
            details.append('Test/Connect button found')
        
        # Check for batch push
        push_btn = page.query_selector('button:has-text("推送"), button:has-text("批量"), button:has-text("Push")')
        if push_btn:
            details.append('Push button found')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Integration Page Buttons', status, '; '.join(details), errors)

def test_forward_page(page):
    """Test forward page."""
    errors = []
    details = []
    
    try:
        login(page)
        page.goto(f'{BASE_URL}/forward', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        
        # Check for add target button
        add_btn = page.query_selector('button:has-text("添加"), button:has-text("新建"), button:has-text("创建")')
        if add_btn:
            add_btn.click()
            page.wait_for_timeout(1000)
            modal = page.query_selector('.n-modal, .n-drawer')
            if modal:
                details.append('Add target modal opened')
                cancel = page.query_selector('.n-modal button:has-text("取消"), .n-drawer button:has-text("取消")')
                if cancel:
                    cancel.click()
                    page.wait_for_timeout(500)
            else:
                errors.append('Add target modal did not appear')
        else:
            details.append('No add button found')
        
        # Check for start/stop buttons
        start_btn = page.query_selector('button:has-text("启动"), button:has-text("开始")')
        stop_btn = page.query_selector('button:has-text("停止"), button:has-text("暂停")')
        if start_btn:
            details.append('Start button found')
        if stop_btn:
            details.append('Stop button found')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Forward Page', status, '; '.join(details), errors)

def test_webhook_page(page):
    """Test webhook page."""
    errors = []
    details = []
    
    try:
        login(page)
        page.goto(f'{BASE_URL}/webhook', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        
        # Check for add webhook button
        add_btn = page.query_selector('button:has-text("添加"), button:has-text("创建"), button:has-text("新建")')
        if add_btn:
            add_btn.click()
            page.wait_for_timeout(1000)
            modal = page.query_selector('.n-modal, .n-drawer')
            if modal:
                details.append('Add webhook modal opened')
                cancel = page.query_selector('.n-modal button:has-text("取消"), .n-drawer button:has-text("取消")')
                if cancel:
                    cancel.click()
                    page.wait_for_timeout(500)
            else:
                errors.append('Add webhook modal did not appear')
        else:
            details.append('No add button found')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Webhook Page', status, '; '.join(details), errors)

def test_recorder_page(page):
    """Test recorder page."""
    errors = []
    details = []
    
    try:
        login(page)
        page.goto(f'{BASE_URL}/recorder', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        
        # Check for start recording button
        start_btn = page.query_selector('button:has-text("开始"), button:has-text("启动"), button:has-text("录制")')
        if start_btn:
            details.append('Start recording button found')
        
        # Check for stats
        cards = page.query_selector_all('.n-card')
        details.append(f'Cards: {len(cards)}')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Recorder Page', status, '; '.join(details), errors)

def test_change_password_modal(page):
    """Test change password modal."""
    errors = []
    details = []
    
    try:
        login(page)
        page.goto(f'{BASE_URL}/', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1000)
        
        # Click user menu
        user_btn = page.query_selector('button[aria-label="User menu"]')
        if user_btn:
            user_btn.click()
            page.wait_for_timeout(500)
            
            # Click change password
            items = page.query_selector_all('.n-dropdown-option')
            for item in items:
                if '密码' in item.inner_text() or 'password' in item.inner_text().lower():
                    item.click()
                    page.wait_for_timeout(1000)
                    break
            
            # Check if modal appeared
            modal = page.query_selector('.n-modal')
            if modal:
                details.append('Change password modal opened')
                
                # Check form fields
                inputs = page.query_selector_all('.n-modal input')
                details.append(f'Form inputs: {len(inputs)}')
                
                # Close modal
                cancel = page.query_selector('.n-modal button:has-text("取消")')
                if cancel:
                    cancel.click()
                    page.wait_for_timeout(500)
            else:
                errors.append('Change password modal did not appear')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Change Password Modal', status, '; '.join(details), errors)

def test_not_found_page(page):
    """Test 404 page."""
    errors = []
    details = []
    
    try:
        login(page)
        page.goto(f'{BASE_URL}/nonexistent-page', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1000)
        
        body = page.inner_text('body')
        if '404' in body or 'NotFound' in body or 'not found' in body.lower() or '不存在' in body:
            details.append('404 page rendered correctly')
        else:
            # Check if redirected to dashboard
            if page.query_selector('.app-layout'):
                details.append('Redirected to dashboard (acceptable)')
            else:
                errors.append('404 page did not render')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('404 Page', status, '; '.join(details), errors)

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        
        print('=== Upload/Download & Edge Case Tests ===\n')
        
        # API-based tests
        test_backup_export_api()
        test_scenario_export_import_api()
        test_recorder_export_api()
        test_test_report_html_api()
        test_role_based_access()
        
        # Browser-based tests
        if login(page):
            test_integration_page_buttons(page)
            test_forward_page(page)
            test_webhook_page(page)
            test_recorder_page(page)
            test_change_password_modal(page)
            test_not_found_page(page)
        
        browser.close()
    
    # Summary
    print('\n' + '='*80)
    print('SUMMARY')
    print('='*80)
    ok = sum(1 for r in results if r['status'] == 'PASS')
    warn = sum(1 for r in results if r['status'] == 'WARN')
    fail = sum(1 for r in results if r['status'] == 'FAIL')
    print(f'Total: {len(results)}, PASS: {ok}, WARN: {warn}, FAIL: {fail}')
    
    if fail > 0:
        print('\nFailed items:')
        for r in results:
            if r['status'] == 'FAIL':
                print(f"  - {r['page']}: {r['errors']}")

if __name__ == '__main__':
    main()
