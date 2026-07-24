"""Full acceptance test for ProtoForge frontend using Playwright."""
import subprocess
import sys
import json
import time
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# First, install playwright if needed
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'playwright'])
    from playwright.sync_api import sync_playwright

BASE_URL = 'http://localhost:5173'
API_URL = 'http://localhost:8000/api/v1'

# All routes to test
ROUTES = [
    ('/', 'Dashboard', '仪表盘'),
    ('/devices', 'Devices', '设备管理'),
    ('/protocols', 'Protocols', '协议服务'),
    ('/scenarios', 'Scenarios', '场景编排'),
    ('/scenario-editor', 'ScenarioEditor', '场景编辑器'),
    ('/templates', 'Templates', '设备模板'),
    ('/marketplace', 'Marketplace', '模板市场'),
    ('/testing', 'Testing', '仿真测试'),
    ('/logs', 'Logs', '调试日志'),
    ('/integration', 'Integration', '联调集成'),
    ('/forward', 'Forward', '数据转发'),
    ('/recorder', 'Recorder', '录制回放'),
    ('/webhook', 'Webhook', 'Webhook'),
    ('/settings', 'Settings', '系统设置'),
    ('/audit', 'Audit', '审计日志'),
    ('/backup', 'Backup', '备份恢复'),
]

results = []

def test_page(page, route, name, menu_name):
    """Test a single page."""
    result = {
        'page': name,
        'route': route,
        'status': 'PASS',
        'errors': [],
        'warnings': [],
        'load_time': 0,
        'buttons_found': 0,
        'details': ''
    }
    
    try:
        # Collect console errors
        console_errors = []
        console_warnings = []
        page.on('console', lambda msg: (
            console_errors.append(msg.text) if msg.type == 'error' else
            console_warnings.append(msg.text) if msg.type == 'warning' else None
        ))
        
        # Collect page errors (uncaught exceptions)
        page_errors = []
        page.on('pageerror', lambda err: page_errors.append(str(err)))
        
        # Navigate to the page
        url = f'{BASE_URL}{route}'
        start_time = time.time()
        response = page.goto(url, wait_until='networkidle', timeout=15000)
        load_time = time.time() - start_time
        result['load_time'] = round(load_time, 2)
        
        if load_time > 3:
            result['warnings'].append(f'Load time {load_time:.2f}s > 3s')
            result['status'] = 'WARN'
        
        # Check for white screen
        body_text = page.inner_text('body')
        if not body_text or len(body_text.strip()) < 10:
            result['errors'].append('White screen detected')
            result['status'] = 'FAIL'
            return result
        
        # Check for 404 resources
        failed_requests = []
        page.on('requestfailed', lambda req: failed_requests.append(f'{req.method} {req.url}'))
        
        # Wait a bit for any async errors
        page.wait_for_timeout(1000)
        
        # Check page errors
        if page_errors:
            result['errors'].extend(page_errors[:3])
            result['status'] = 'FAIL'
        
        # Check console errors (filter out irrelevant ones)
        relevant_errors = [e for e in console_errors 
                          if 'localhost:5173' in e or 'localhost:8000' in e or 'protoforge' in e.lower()]
        if relevant_errors:
            result['errors'].extend(relevant_errors[:3])
            result['status'] = 'FAIL'
        
        # Count interactive elements
        buttons = page.query_selector_all('button')
        links = page.query_selector_all('a')
        inputs = page.query_selector_all('input, textarea, select')
        result['buttons_found'] = len(buttons) + len(links)
        result['details'] = f'{len(buttons)} buttons, {len(links)} links, {len(inputs)} inputs'
        
        # Check if the menu name appears in the page (breadcrumb)
        if menu_name:
            try:
                breadcrumb = page.inner_text('.app-breadcrumb')
                if menu_name not in breadcrumb and route != '/':
                    result['warnings'].append(f'Menu name "{menu_name}" not in breadcrumb')
            except:
                pass  # Breadcrumb might not exist on some pages
        
        # Take screenshot
        screenshot_path = f'e:/硕腾网络/PyGBSentry/ProtoForge/.convergeloop/screenshots/{name.lower()}.png'
        page.screenshot(path=screenshot_path, full_page=True)
        
    except Exception as e:
        result['errors'].append(str(e)[:200])
        result['status'] = '❌'
    
    return result

def test_login(page):
    """Test login functionality."""
    result = {'page': 'Login', 'status': '✅', 'errors': [], 'details': ''}
    try:
        page.goto(f'{BASE_URL}/', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1000)
        
        # Check if login form is visible
        username_input = page.query_selector('input[placeholder*="用户名"]')
        password_input = page.query_selector('input[placeholder*="密码"]')
        
        if not username_input or not password_input:
            # Maybe already logged in
            if page.query_selector('.app-layout'):
                result['details'] = 'Already logged in'
                return result
            result['errors'].append('Login form not found')
            result['status'] = 'FAIL'
            return result
        
        # Fill login form
        username_input.fill('admin')
        password_input.fill('admin')
        
        # Click login button
        login_btn = page.query_selector('button:has-text("登")')
        if login_btn:
            login_btn.click()
        else:
            # Try pressing Enter
            password_input.press('Enter')
        
        page.wait_for_timeout(3000)
        
        # Check if login succeeded
        if page.query_selector('.app-layout') or page.query_selector('.n-layout-sider'):
            result['details'] = 'Login successful'
        else:
            result['errors'].append('Login failed - no app layout after login')
            result['status'] = 'FAIL'
            
    except Exception as e:
        result['errors'].append(str(e)[:200])
        result['status'] = '❌'
    
    return result

def test_form_validation(page):
    """Test form validation on device creation."""
    result = {'page': 'Form Validation', 'status': '✅', 'errors': [], 'details': ''}
    try:
        # Go to devices page
        page.goto(f'{BASE_URL}/devices', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1000)
        
        # Try to find and click "快速创建" button
        quick_create = page.query_selector('button:has-text("快速创建")')
        if quick_create:
            quick_create.click()
            page.wait_for_timeout(1000)
            
            # Check if modal appeared
            modal = page.query_selector('.n-modal, .n-drawer')
            if modal:
                result['details'] = 'Quick create modal opened'
                # Try to submit without filling required fields
                submit_btn = page.query_selector('.n-modal button:has-text("确定"), .n-modal button:has-text("创建"), .n-drawer button:has-text("确定"), .n-drawer button:has-text("创建")')
                if submit_btn:
                    submit_btn.click()
                    page.wait_for_timeout(500)
                    # Check for validation error
                    error_msg = page.query_selector('.n-form-item-feedback__line, .n-form-item__feedback')
                    if error_msg and error_msg.inner_text().strip():
                        result['details'] += ', validation works'
                    else:
                        result['warnings'].append('No validation error shown for empty form')
                
                # Close modal
                close_btn = page.query_selector('.n-modal .n-button:has-text("取消"), .n-drawer .n-button:has-text("取消")')
                if close_btn:
                    close_btn.click()
            else:
                result['warnings'].append('Quick create modal did not appear')
        else:
            result['details'] = 'No quick create button found'
            
    except Exception as e:
        result['errors'].append(str(e)[:200])
        result['status'] = '❌'
    
    return result

def test_search(page):
    """Test global search functionality."""
    result = {'page': 'Search', 'status': '✅', 'errors': [], 'details': ''}
    try:
        page.goto(f'{BASE_URL}/', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1000)
        
        search_input = page.query_selector('input[placeholder*="搜索"]')
        if search_input:
            search_input.fill('modbus')
            page.wait_for_timeout(1000)
            
            # Check for search results
            options = page.query_selector_all('.n-auto-complete .n-auto-complete-menu__content, .n-auto-complete__menu')
            if options:
                result['details'] = f'Search returned results'
            else:
                # Check if any dropdown appeared
                dropdown = page.query_selector('.n-auto-complete__menu')
                result['details'] = 'Search triggered, dropdown may or may not have results'
            
            # Clear search
            search_input.fill('')
            result['details'] += ', cleared'
        else:
            result['warnings'].append('Search input not found')
            
    except Exception as e:
        result['errors'].append(str(e)[:200])
        result['status'] = '❌'
    
    return result

def test_route_guard(page):
    """Test route guard - access without token should redirect to login."""
    result = {'page': 'Route Guard', 'status': '✅', 'errors': [], 'details': ''}
    try:
        # Clear localStorage to simulate logged out state
        page.goto(f'{BASE_URL}/', wait_until='networkidle', timeout=15000)
        page.evaluate('localStorage.clear()')
        
        # Try to access a protected route
        page.goto(f'{BASE_URL}/devices', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1000)
        
        url = page.url
        # Should be redirected to / (login page)
        if url.endswith('/') or url.endswith('/devices') == False:
            result['details'] = f'Redirected to {url} (route guard works)'
        else:
            # Check if login form is shown
            login_form = page.query_selector('input[placeholder*="用户名"]')
            if login_form:
                result['details'] = 'Login form shown (route guard works)'
            else:
                result['warnings'].append(f'Accessed /devices without auth, URL: {url}')
                
    except Exception as e:
        result['errors'].append(str(e)[:200])
        result['status'] = '❌'
    
    return result

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        
        # Ensure screenshots directory exists
        import os
        os.makedirs('e:/硕腾网络/PyGBSentry/ProtoForge/.convergeloop/screenshots', exist_ok=True)
        
        # Test login first
        print('=== Testing Login ===')
        login_result = test_login(page)
        results.append(login_result)
        print(f"Login: {login_result['status']} - {login_result.get('details', '')}")
        if login_result['errors']:
            print(f"  Errors: {login_result['errors']}")
        
        # Test each page
        print('\n=== Testing Pages ===')
        for route, name, menu_name in ROUTES:
            result = test_page(page, route, name, menu_name)
            results.append(result)
            status_icon = result['status']
            load_time = result.get('load_time', '?')
            details = result.get('details', '')
            errors = result.get('errors', [])
            warnings = result.get('warnings', [])
            print(f"{status_icon} {name} ({route}) - {load_time}s - {details}")
            if errors:
                for e in errors:
                    print(f"  ERROR: {e}")
            if warnings:
                for w in warnings:
                    print(f"  WARN: {w}")
        
        # Test form validation
        print('\n=== Testing Form Validation ===')
        # Re-login first since route guard test cleared localStorage
        test_login(page)
        form_result = test_form_validation(page)
        results.append(form_result)
        print(f"{form_result['status']} {form_result['page']} - {form_result.get('details', '')}")
        if form_result['errors']:
            print(f"  Errors: {form_result['errors']}")
        
        # Test search
        print('\n=== Testing Search ===')
        search_result = test_search(page)
        results.append(search_result)
        print(f"{search_result['status']} {search_result['page']} - {search_result.get('details', '')}")
        
        # Test route guard
        print('\n=== Testing Route Guard ===')
        guard_result = test_route_guard(page)
        results.append(guard_result)
        print(f"{guard_result['status']} {guard_result['page']} - {guard_result.get('details', '')}")
        
        # Re-login for any further tests
        test_login(page)
        
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
                print(f"  - {r['page']}: {r.get('errors', [])}")
    
    if warn > 0:
        print('\nWarnings:')
        for r in results:
            if r['status'] == 'WARN':
                print(f"  - {r['page']}: {r.get('warnings', [])}")

if __name__ == '__main__':
    main()
