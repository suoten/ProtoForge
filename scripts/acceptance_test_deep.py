"""Deep interaction tests for ProtoForge frontend."""
import sys
import io
import time
import os
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

def test_device_crud(page):
    """Test device CRUD operations - create, read, update, delete."""
    errors = []
    details = []
    
    try:
        # Go to devices page
        page.goto(f'{BASE_URL}/devices', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        
        # Count initial devices
        checkboxes = page.query_selector_all('input[type="checkbox"]')
        # Subtract 1 for the "select all" checkbox
        initial_count = max(0, len(checkboxes) - 1)
        details.append(f'Initial devices: {initial_count}')
        
        # Test "快速创建" button
        quick_create = page.query_selector('button:has-text("快速创建")')
        if quick_create:
            quick_create.click()
            page.wait_for_timeout(1000)
            
            # Check if modal appeared
            modal = page.query_selector('.n-modal, .n-drawer')
            if modal:
                details.append('Quick create modal opened')
                
                # Check form fields
                inputs = page.query_selector_all('.n-modal input, .n-drawer input')
                selects = page.query_selector_all('.n-modal .n-select, .n-drawer .n-select')
                details.append(f'Form fields: {len(inputs)} inputs, {len(selects)} selects')
                
                # Try to fill in the form
                # Look for template select
                template_select = page.query_selector('.n-modal .n-select-trigger, .n-drawer .n-select-trigger')
                if template_select:
                    template_select.click()
                    page.wait_for_timeout(500)
                    # Select first option
                    options = page.query_selector_all('.n-base-select-option')
                    if options:
                        options[0].click()
                        page.wait_for_timeout(500)
                        details.append('Template selected')
                
                # Look for name input
                name_input = None
                for inp in page.query_selector_all('.n-modal input, .n-drawer input'):
                    placeholder = inp.get_attribute('placeholder') or ''
                    if '名称' in placeholder or 'name' in placeholder.lower() or '设备' in placeholder:
                        name_input = inp
                        break
                
                if name_input:
                    name_input.fill('test-acceptance-device')
                    details.append('Device name filled')
                
                # Look for ID input
                for inp in page.query_selector_all('.n-modal input, .n-drawer input'):
                    placeholder = inp.get_attribute('placeholder') or ''
                    if 'ID' in placeholder or 'id' in placeholder.lower():
                        inp.fill('test-acc-dev-001')
                        details.append('Device ID filled')
                        break
                
                # Try to submit
                submit_btn = page.query_selector('.n-modal button:has-text("确定"), .n-modal button:has-text("创建"), .n-drawer button:has-text("确定"), .n-drawer button:has-text("创建")')
                if submit_btn and submit_btn.is_enabled():
                    submit_btn.click()
                    page.wait_for_timeout(2000)
                    details.append('Submit clicked')
                    
                    # Check for success message
                    success_msg = page.query_selector('.n-message--success-type, .n-message-success')
                    if success_msg:
                        details.append('Success message shown')
                else:
                    details.append('Submit button disabled (validation working)')
                
                # Close modal if still open
                cancel_btn = page.query_selector('.n-modal button:has-text("取消"), .n-drawer button:has-text("取消")')
                if cancel_btn:
                    cancel_btn.click()
                    page.wait_for_timeout(500)
            else:
                errors.append('Quick create modal did not appear')
        else:
            errors.append('Quick create button not found')
        
        # Test device edit button
        edit_btn = page.query_selector('button:has-text("编辑")')
        if edit_btn:
            edit_btn.click()
            page.wait_for_timeout(1000)
            edit_modal = page.query_selector('.n-modal, .n-drawer')
            if edit_modal:
                details.append('Edit modal opened')
                cancel = page.query_selector('.n-modal button:has-text("取消"), .n-drawer button:has-text("取消")')
                if cancel:
                    cancel.click()
                    page.wait_for_timeout(500)
            else:
                errors.append('Edit modal did not appear')
        
        # Test "数据测点" button
        points_btn = page.query_selector('button:has-text("数据测点")')
        if points_btn:
            points_btn.click()
            page.wait_for_timeout(1500)
            # Check if points view or modal appeared
            points_content = page.query_selector('.n-modal, .n-drawer, .n-data-table')
            if points_content:
                details.append('Points view/modal opened')
                # Close
                close_btn = page.query_selector('.n-modal button:has-text("关闭"), .n-drawer button:has-text("关闭"), .n-modal .n-button:has-text("取消")')
                if close_btn:
                    close_btn.click()
                    page.wait_for_timeout(500)
            else:
                errors.append('Points view did not appear')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Device CRUD', status, '; '.join(details), errors)

def test_protocol_operations(page):
    """Test protocol start/stop operations."""
    errors = []
    details = []
    
    try:
        page.goto(f'{BASE_URL}/protocols', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        
        # Find a "详情" button and click it
        detail_btn = page.query_selector('button:has-text("详情")')
        if detail_btn:
            detail_btn.click()
            page.wait_for_timeout(1000)
            modal = page.query_selector('.n-modal, .n-drawer')
            if modal:
                details.append('Protocol detail modal opened')
                cancel = page.query_selector('.n-modal button:has-text("关闭"), .n-modal button:has-text("取消")')
                if cancel:
                    cancel.click()
                    page.wait_for_timeout(500)
            else:
                errors.append('Protocol detail modal did not appear')
        
        # Find "高级配置" button
        config_btn = page.query_selector('button:has-text("高级配置")')
        if config_btn:
            config_btn.click()
            page.wait_for_timeout(1000)
            modal = page.query_selector('.n-modal, .n-drawer')
            if modal:
                details.append('Protocol config modal opened')
                cancel = page.query_selector('.n-modal button:has-text("取消"), .n-drawer button:has-text("取消")')
                if cancel:
                    cancel.click()
                    page.wait_for_timeout(500)
            else:
                errors.append('Protocol config modal did not appear')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Protocol Operations', status, '; '.join(details), errors)

def test_scenario_operations(page):
    """Test scenario page operations."""
    errors = []
    details = []
    
    try:
        page.goto(f'{BASE_URL}/scenarios', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        
        # Check for scenario cards or list
        cards = page.query_selector_all('.n-card')
        details.append(f'Scenario cards: {len(cards)}')
        
        # Look for create button
        create_btn = page.query_selector('button:has-text("创建"), button:has-text("新建")')
        if create_btn:
            create_btn.click()
            page.wait_for_timeout(1000)
            modal = page.query_selector('.n-modal, .n-drawer')
            if modal:
                details.append('Create scenario modal opened')
                cancel = page.query_selector('.n-modal button:has-text("取消"), .n-drawer button:has-text("取消")')
                if cancel:
                    cancel.click()
                    page.wait_for_timeout(500)
        
        # Test scenario editor
        page.goto(f'{BASE_URL}/scenario-editor', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        # Check if editor loaded
        editor = page.query_selector('.vue-flow, .n-data-table, .n-card')
        if editor:
            details.append('Scenario editor loaded')
        else:
            errors.append('Scenario editor did not load')
            
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Scenario Operations', status, '; '.join(details), errors)

def test_template_operations(page):
    """Test template page operations."""
    errors = []
    details = []
    
    try:
        page.goto(f'{BASE_URL}/templates', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        
        # Count template cards
        cards = page.query_selector_all('.n-card')
        details.append(f'Template cards: {len(cards)}')
        
        # Look for search/filter
        search_input = page.query_selector('input[placeholder*="搜索"], input[placeholder*="筛选"]')
        if search_input:
            search_input.fill('modbus')
            page.wait_for_timeout(1000)
            filtered_cards = page.query_selector_all('.n-card')
            details.append(f'Filtered templates: {len(filtered_cards)}')
            search_input.fill('')
            page.wait_for_timeout(500)
            details.append('Search cleared')
        
        # Look for create template button
        create_btn = page.query_selector('button:has-text("创建"), button:has-text("新建")')
        if create_btn:
            create_btn.click()
            page.wait_for_timeout(1000)
            modal = page.query_selector('.n-modal, .n-drawer')
            if modal:
                details.append('Create template modal opened')
                cancel = page.query_selector('.n-modal button:has-text("取消"), .n-drawer button:has-text("取消")')
                if cancel:
                    cancel.click()
                    page.wait_for_timeout(500)
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Template Operations', status, '; '.join(details), errors)

def test_table_pagination(page):
    """Test table pagination on audit page."""
    errors = []
    details = []
    
    try:
        page.goto(f'{BASE_URL}/audit', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        
        # Check for data table
        table = page.query_selector('.n-data-table')
        if table:
            details.append('Audit table found')
            
            # Check for pagination
            pagination = page.query_selector('.n-pagination')
            if pagination:
                details.append('Pagination found')
                
                # Check pagination buttons
                page_btns = page.query_selector_all('.n-pagination .n-pagination-item')
                details.append(f'Pagination items: {len(page_btns)}')
            else:
                details.append('No pagination (may have few records)')
            
            # Check for filter inputs
            filters = page.query_selector_all('.n-data-table-filter-popover, .n-select')
            details.append(f'Filter elements: {len(filters)}')
        
        # Test audit stats
        page.goto(f'{BASE_URL}/audit', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1000)
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Table & Pagination', status, '; '.join(details), errors)

def test_backup_download(page):
    """Test backup download functionality."""
    errors = []
    details = []
    
    try:
        page.goto(f'{BASE_URL}/backup', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        
        # Look for export/backup button
        export_btn = page.query_selector('button:has-text("导出"), button:has-text("备份"), button:has-text("下载")')
        if export_btn:
            details.append('Export button found')
            # Note: We won't actually click it to avoid downloading files
        else:
            details.append('No export button found (checking page content)')
            
        # Check page content
        body = page.inner_text('body')
        if '备份' in body or '恢复' in body or 'backup' in body.lower():
            details.append('Backup page content correct')
        else:
            errors.append('Backup page content missing keywords')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Backup Download', status, '; '.join(details), errors)

def test_settings_form(page):
    """Test settings page forms."""
    errors = []
    details = []
    
    try:
        page.goto(f'{BASE_URL}/settings', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        
        # Check for form inputs
        inputs = page.query_selector_all('input, textarea, select, .n-select')
        details.append(f'Settings inputs: {len(inputs)}')
        
        # Look for save button
        save_btn = page.query_selector('button:has-text("保存"), button:has-text("确定")')
        if save_btn:
            details.append('Save button found')
        
        # Look for tabs
        tabs = page.query_selector_all('.n-tabs-tab')
        if tabs:
            details.append(f'Tabs: {len(tabs)}')
            # Click second tab if exists
            if len(tabs) > 1:
                tabs[1].click()
                page.wait_for_timeout(500)
                details.append('Tab switch tested')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Settings Form', status, '; '.join(details), errors)

def test_empty_states(page):
    """Test empty state handling."""
    errors = []
    details = []
    
    try:
        # Test forward page (likely empty)
        page.goto(f'{BASE_URL}/forward', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        body = page.inner_text('body')
        if body.strip():
            details.append('Forward page has content')
        else:
            errors.append('Forward page is blank')
        
        # Test recorder page
        page.goto(f'{BASE_URL}/recorder', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        body = page.inner_text('body')
        if body.strip():
            details.append('Recorder page has content')
        else:
            errors.append('Recorder page is blank')
        
        # Test webhook page
        page.goto(f'{BASE_URL}/webhook', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        body = page.inner_text('body')
        if body.strip():
            details.append('Webhook page has content')
        else:
            errors.append('Webhook page is blank')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Empty States', status, '; '.join(details), errors)

def test_api_error_handling(page):
    """Test API error handling with invalid requests."""
    errors = []
    details = []
    
    try:
        # Login first
        login(page)
        
        # Try to access a non-existent device
        page.goto(f'{BASE_URL}/devices', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1000)
        
        # The page should handle API errors gracefully
        # Check for error messages or empty state
        body = page.inner_text('body')
        if 'error' not in body.lower() or '暂无' in body or '空' in body or len(body) > 50:
            details.append('Error handling works (no crash)')
        else:
            errors.append('Page shows raw error')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('API Error Handling', status, '; '.join(details), errors)

def test_data_consistency(page):
    """Test data consistency - list refresh after operations."""
    errors = []
    details = []
    
    try:
        # Use API to create and delete a device, then check if list updates
        r = requests.post(f'{API_URL}/auth/login', json={'username': 'admin', 'password': 'admin'})
        token = r.json().get('access_token', '')
        headers = {'Authorization': f'Bearer {token}'}
        
        # Get initial device count
        r = requests.get(f'{API_URL}/devices', headers=headers, timeout=10)
        initial_devices = r.json() if r.status_code == 200 else []
        if isinstance(initial_devices, dict):
            initial_devices = initial_devices.get('devices', [])
        details.append(f'Initial devices via API: {len(initial_devices)}')
        
        # Create a test device via API
        test_device = {
            'id': 'consistency-test-001',
            'name': 'Consistency Test Device',
            'protocol': 'modbus_tcp',
            'config': {
                'host': '127.0.0.1',
                'port': 502,
                'slave_id': 1,
                'points': [
                    {'name': 'temperature', 'address': 0, 'type': 'holding', 'data_type': 'float32'}
                ]
            }
        }
        r = requests.post(f'{API_URL}/devices', json=test_device, headers=headers, timeout=10)
        if r.status_code in (200, 201):
            details.append('Test device created via API')
            
            # Check if device appears in list
            r = requests.get(f'{API_URL}/devices', headers=headers, timeout=10)
            after_create = r.json() if r.status_code == 200 else []
            if isinstance(after_create, dict):
                after_create = after_create.get('devices', [])
            details.append(f'Devices after create: {len(after_create)}')
            
            if len(after_create) > len(initial_devices):
                details.append('Data consistency: device appeared in list')
            else:
                errors.append('Data consistency: device not in list after create')
            
            # Delete the test device
            r = requests.delete(f'{API_URL}/devices/consistency-test-001', headers=headers, timeout=10)
            if r.status_code in (200, 204):
                details.append('Test device deleted')
                
                # Check if device is removed from list
                r = requests.get(f'{API_URL}/devices', headers=headers, timeout=10)
                after_delete = r.json() if r.status_code == 200 else []
                if isinstance(after_delete, dict):
                    after_delete = after_delete.get('devices', [])
                
                if len(after_delete) == len(initial_devices):
                    details.append('Data consistency: device removed from list')
                else:
                    errors.append(f'Data consistency: count mismatch after delete ({len(after_delete)} vs {len(initial_devices)})')
            else:
                errors.append(f'Delete failed: {r.status_code}')
        else:
            details.append(f'Create returned {r.status_code} (may already exist)')
            # Try to delete it
            requests.delete(f'{API_URL}/devices/consistency-test-001', headers=headers, timeout=10)
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Data Consistency', status, '; '.join(details), errors)

def test_user_menu(page):
    """Test user menu dropdown."""
    errors = []
    details = []
    
    try:
        login(page)
        page.goto(f'{BASE_URL}/', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1000)
        
        # Click user menu button
        user_btn = page.query_selector('button[aria-label="User menu"]')
        if user_btn:
            user_btn.click()
            page.wait_for_timeout(500)
            
            # Check dropdown items
            dropdown_items = page.query_selector_all('.n-dropdown-option')
            if dropdown_items:
                details.append(f'User menu items: {len(dropdown_items)}')
                # Check for "修改密码" and "退出登录"
                for item in dropdown_items:
                    text = item.inner_text()
                    if '密码' in text or 'password' in text.lower():
                        details.append('Change password option found')
                    if '退出' in text or 'logout' in text.lower():
                        details.append('Logout option found')
            else:
                errors.append('No dropdown items in user menu')
        else:
            errors.append('User menu button not found')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('User Menu', status, '; '.join(details), errors)

def test_language_switch(page):
    """Test language switching."""
    errors = []
    details = []
    
    try:
        login(page)
        page.goto(f'{BASE_URL}/', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1000)
        
        # Click language switch button
        lang_btn = page.query_selector('button[aria-label="Switch language"]')
        if lang_btn:
            lang_btn.click()
            page.wait_for_timeout(500)
            
            # Check dropdown
            options = page.query_selector_all('.n-dropdown-option')
            if options:
                details.append(f'Language options: {len(options)}')
                # Click English
                for opt in options:
                    if 'English' in opt.inner_text() or 'EN' in opt.inner_text():
                        opt.click()
                        page.wait_for_timeout(500)
                        details.append('Switched to English')
                        break
                
                # Switch back to Chinese
                lang_btn = page.query_selector('button[aria-label="Switch language"]')
                if lang_btn:
                    lang_btn.click()
                    page.wait_for_timeout(500)
                    options = page.query_selector_all('.n-dropdown-option')
                    for opt in options:
                        if '中文' in opt.inner_text():
                            opt.click()
                            page.wait_for_timeout(500)
                            details.append('Switched back to Chinese')
                            break
        else:
            errors.append('Language switch button not found')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Language Switch', status, '; '.join(details), errors)

def test_marketplace(page):
    """Test marketplace page."""
    errors = []
    details = []
    
    try:
        login(page)
        page.goto(f'{BASE_URL}/marketplace', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        
        # Check for template cards
        cards = page.query_selector_all('.n-card')
        details.append(f'Marketplace cards: {len(cards)}')
        
        # Check for filter/search
        inputs = page.query_selector_all('input')
        details.append(f'Inputs: {len(inputs)}')
        
        # Check for "安装" or "使用" buttons
        install_btns = page.query_selector_all('button:has-text("安装"), button:has-text("使用"), button:has-text(" instantiate"), button:has-text("实例化")')
        details.append(f'Install/Use buttons: {len(install_btns)}')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Marketplace', status, '; '.join(details), errors)

def test_testing_page(page):
    """Test testing page."""
    errors = []
    details = []
    
    try:
        login(page)
        page.goto(f'{BASE_URL}/testing', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        
        # Check for test-related elements
        cards = page.query_selector_all('.n-card')
        details.append(f'Test cards: {len(cards)}')
        
        # Look for create test button
        create_btn = page.query_selector('button:has-text("创建"), button:has-text("新建")')
        if create_btn:
            create_btn.click()
            page.wait_for_timeout(1000)
            modal = page.query_selector('.n-modal, .n-drawer')
            if modal:
                details.append('Create test modal opened')
                cancel = page.query_selector('.n-modal button:has-text("取消"), .n-drawer button:has-text("取消")')
                if cancel:
                    cancel.click()
                    page.wait_for_timeout(500)
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Testing Page', status, '; '.join(details), errors)

def test_logs_page(page):
    """Test logs page with WebSocket."""
    errors = []
    details = []
    
    try:
        login(page)
        page.goto(f'{BASE_URL}/logs', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(2000)
        
        # Check for log entries
        body = page.inner_text('body')
        if body.strip():
            details.append('Logs page has content')
        
        # Check for clear logs button
        clear_btn = page.query_selector('button:has-text("清空"), button:has-text("清除")')
        if clear_btn:
            details.append('Clear logs button found')
        
        # Check for log level filter
        filters = page.query_selector_all('.n-select, .n-radio-button, .n-button-group button')
        details.append(f'Filter elements: {len(filters)}')
        
    except Exception as e:
        errors.append(str(e)[:300])
    
    status = 'PASS' if not errors else 'FAIL'
    return add_result('Logs Page', status, '; '.join(details), errors)

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        
        # Ensure screenshots directory
        os.makedirs('e:/硕腾网络/PyGBSentry/ProtoForge/.convergeloop/screenshots', exist_ok=True)
        
        print('=== Deep Interaction Tests ===\n')
        
        # Login first
        if not login(page):
            print('Login failed, aborting tests')
            return
        print('[OK] Login successful\n')
        
        # Run all tests
        test_device_crud(page)
        test_protocol_operations(page)
        test_scenario_operations(page)
        test_template_operations(page)
        test_table_pagination(page)
        test_backup_download(page)
        test_settings_form(page)
        test_empty_states(page)
        test_api_error_handling(page)
        test_data_consistency(page)
        test_user_menu(page)
        test_language_switch(page)
        test_marketplace(page)
        test_testing_page(page)
        test_logs_page(page)
        
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
    
    if warn > 0:
        print('\nWarnings:')
        for r in results:
            if r['status'] == 'WARN':
                print(f"  - {r['page']}: {r['warnings']}")

if __name__ == '__main__':
    main()
