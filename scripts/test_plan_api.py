"""Quick API test for test plan and compliance endpoints."""
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

# 1. List test plans
def t1():
    r = requests.get(f'{base}/test-plans')
    assert r.status_code == 200
    assert 'plans' in r.json()
test('List test plans', t1)

# 2. Create test plan
plan_id = [None]
def t2():
    r = requests.post(f'{base}/test-plans', json={
        'name': 'S7 Protocol Test',
        'version': '2.0.0',
        'description': 'S7 comprehensive testing',
        'test_suite_ids': [],
        'status': 'draft'
    })
    assert r.status_code == 200
    plan_id[0] = r.json()['id']
test('Create test plan', t2)

# 3. Get plan
def t3():
    r = requests.get(f'{base}/test-plans/{plan_id[0]}')
    assert r.status_code == 200
    assert r.json()['version'] == '2.0.0'
test('Get test plan', t3)

# 4. Update plan
def t4():
    r = requests.put(f'{base}/test-plans/{plan_id[0]}', json={'status': 'active'})
    assert r.status_code == 200
    assert r.json()['status'] == 'active'
test('Update test plan', t4)

# 5. Run plan
run_id = [None]
def t5():
    r = requests.post(f'{base}/test-plans/{plan_id[0]}/run', json={'trigger_source': 'manual'})
    assert r.status_code == 200
    run_id[0] = r.json()['id']
    assert r.json()['status'] in ('passed', 'failed', 'error')
test('Run test plan', t5)

# 6. List runs
def t6():
    r = requests.get(f'{base}/test-plans/{plan_id[0]}/runs')
    assert r.status_code == 200
    assert len(r.json()['runs']) >= 1
test('List plan runs', t6)

# 7. Get run detail
def t7():
    r = requests.get(f'{base}/test-runs/{run_id[0]}')
    assert r.status_code == 200
    assert r.json()['id'] == run_id[0]
test('Get run detail', t7)

# 8. JSON report
def t8():
    r = requests.get(f'{base}/test-runs/{run_id[0]}/report?format=json')
    assert r.status_code == 200
    assert 'summary' in r.json()
test('Get JSON report', t8)

# 9. JUnit report
def t9():
    r = requests.get(f'{base}/test-runs/{run_id[0]}/report?format=junit')
    assert r.status_code == 200
    assert 'testsuites' in r.text
test('Get JUnit report', t9)

# 10. Clone plan
clone_id = [None]
def t10():
    r = requests.post(f'{base}/test-plans/{plan_id[0]}/clone', json={'name': 'S7 Clone'})
    assert r.status_code == 200
    clone_id[0] = r.json()['id']
test('Clone test plan', t10)

# 11. Delete clone
def t11():
    r = requests.delete(f'{base}/test-plans/{clone_id[0]}')
    assert r.status_code == 200
test('Delete test plan', t11)

# 12. List compliance protocols
def t12():
    r = requests.get(f'{base}/compliance/protocols')
    assert r.status_code == 200
    assert len(r.json()['protocols']) >= 5
test('List compliance protocols', t12)

# 13. Get S7 rules
def t13():
    r = requests.get(f'{base}/compliance/rules/s7')
    assert r.status_code == 200
    assert len(r.json()['rules']) >= 3
test('Get S7 compliance rules', t13)

# 14. Run compliance check
def t14():
    r = requests.post(f'{base}/compliance/check', json={'protocol': 's7'})
    assert r.status_code == 200
    assert 'compliance_score' in r.json()
test('Run compliance check', t14)

# 15. List compliance reports
def t15():
    r = requests.get(f'{base}/compliance/reports')
    assert r.status_code == 200
    assert len(r.json()['reports']) >= 1
test('List compliance reports', t15)

# 16. Get compliance report by ID
report_id = [None]
def t16():
    r = requests.get(f'{base}/compliance/reports')
    report_id[0] = r.json()['reports'][0]['id']
    r2 = requests.get(f'{base}/compliance/reports/{report_id[0]}')
    assert r2.status_code == 200
test('Get compliance report detail', t16)

# 17. HTML report
def t17():
    r = requests.get(f'{base}/test-runs/{run_id[0]}/report?format=html')
    assert r.status_code == 200
    assert '<html' in r.text.lower()
test('Get HTML report', t17)

# 18. Get rules for unsupported protocol
def t18():
    r = requests.get(f'{base}/compliance/rules/nonexistent')
    assert r.status_code == 404
test('Get rules for unsupported protocol (404)', t18)

# 19. Delete original plan
def t19():
    r = requests.delete(f'{base}/test-plans/{plan_id[0]}')
    assert r.status_code == 200
test('Delete original plan', t19)

# 20. Verify deletion
def t20():
    r = requests.get(f'{base}/test-plans/{plan_id[0]}')
    assert r.status_code == 404
test('Verify deletion (404)', t20)

print(f'\n=== Results: {passed} passed, {failed} failed ===')
if failed > 0:
    sys.exit(1)
