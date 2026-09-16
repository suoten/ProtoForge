"""End-to-end test: Create suite + case -> Create plan -> Run plan -> Verify report."""
import requests
import sys

base = 'http://127.0.0.1:8000/api/v1'
passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f'  PASS: {name}')
        passed += 1
    except Exception as e:
        print(f'  FAIL: {name}: {e}')
        failed += 1

# Step 1: Create a test case
case_id = [None]
def t1():
    r = requests.post(f'{base}/tests/cases', json={
        'name': 'E2E Health Check',
        'description': 'Verify API health endpoint',
        'tags': ['e2e'],
        'steps': [{
            'name': 'Call /health',
            'action': 'http_request',
            'params': {'method': 'GET', 'url': '/health'},
            'assertions': [{'type': 'status_code', 'expected': 200, 'message': 'Health OK'}]
        }]
    })
    assert r.status_code == 200, r.text
    case_id[0] = r.json()['id']
test('Create test case', t1)

# Step 2: Create a test suite referencing that case
suite_id = [None]
def t2():
    r = requests.post(f'{base}/tests/suites', json={
        'name': 'E2E Basic Suite',
        'description': 'Basic E2E test suite',
        'test_case_ids': [case_id[0]],
        'tags': ['e2e']
    })
    assert r.status_code == 200, r.text
    suite_id[0] = r.json()['id']
test('Create test suite', t2)

# Step 3: Create a test plan referencing that suite
plan_id = [None]
def t3():
    r = requests.post(f'{base}/test-plans', json={
        'name': 'E2E Full Plan',
        'version': '1.0.0',
        'description': 'Full end-to-end test plan',
        'test_suite_ids': [suite_id[0]],
        'status': 'active'
    })
    assert r.status_code == 200, r.text
    plan_id[0] = r.json()['id']
test('Create test plan with suite', t3)

# Step 4: Run the plan
run_id = [None]
def t4():
    r = requests.post(f'{base}/test-plans/{plan_id[0]}/run', json={'trigger_source': 'manual'})
    assert r.status_code == 200, r.text
    run_id[0] = r.json()['id']
    data = r.json()
    print(f'    Run status: {data["status"]}')
    print(f'    Results: total={data["results_summary"]["total"]}, passed={data["results_summary"]["passed"]}')
    assert data['status'] in ('passed', 'failed', 'error')
test('Run test plan with suite', t4)

# Step 5: Verify run details
def t5():
    r = requests.get(f'{base}/test-runs/{run_id[0]}')
    assert r.status_code == 200
    data = r.json()
    assert data['plan_id'] == plan_id[0]
    assert len(data['results_summary']['suite_reports']) > 0
    suite_report = data['results_summary']['suite_reports'][0]
    print(f'    Suite: {suite_report["suite_name"]}, status: {suite_report["status"]}')
test('Verify run details with suite reports', t5)

# Step 6: Get JUnit XML
def t6():
    r = requests.get(f'{base}/test-runs/{run_id[0]}/report?format=junit')
    assert r.status_code == 200
    assert 'testsuites' in r.text
    assert 'testsuite' in r.text
    print(f'    JUnit XML length: {len(r.text)} chars')
test('Get JUnit XML with actual test results', t6)

# Step 7: Get JSON report
def t7():
    r = requests.get(f'{base}/test-runs/{run_id[0]}/report?format=json')
    assert r.status_code == 200
    data = r.json()
    assert data['summary']['total'] > 0
    print(f'    JSON report: {data["summary"]["total"]} tests, {data["summary"]["passed"]} passed')
test('Get JSON report with results', t7)

# Step 8: List runs for plan
def t8():
    r = requests.get(f'{base}/test-plans/{plan_id[0]}/runs')
    assert r.status_code == 200
    assert len(r.json()['runs']) >= 1
test('List plan runs with history', t8)

# Step 9: Run compliance check on recent messages
def t9():
    r = requests.post(f'{base}/compliance/check', json={'protocol': 'modbus_tcp'})
    assert r.status_code == 200
    data = r.json()
    print(f'    Compliance: score={data["compliance_score"]}, messages={data["total_messages"]}')
test('Run compliance check', t9)

# Step 10: Cleanup
def t10():
    requests.delete(f'{base}/test-plans/{plan_id[0]}')
    requests.delete(f'{base}/tests/suites/{suite_id[0]}')
    requests.delete(f'{base}/tests/cases/{case_id[0]}')
test('Cleanup test data', t10)

print(f'\n=== E2E Results: {passed} passed, {failed} failed ===')
if failed > 0:
    sys.exit(1)
