"""Quick API test for new features."""
import httpx
import time
import sys

BASE = "http://127.0.0.1:8080/api/v1"
# Disable proxy to avoid "Invalid HTTP request received"
client = httpx.Client(proxy=None, timeout=15)

def test_protocols():
    r = client.get(f"{BASE}/protocols")
    protocols = r.json().get("protocols", [])
    print(f"Total protocols: {len(protocols)}")
    new_names = {"dlt645", "cjt188", "custom_tcp", "custom_udp", "s7plus"}
    found = {p["name"] for p in protocols if p["name"] in new_names}
    missing = new_names - found
    if missing:
        print(f"FAIL: Missing protocols: {missing}")
        return False
    print("PASS: All 5 new protocols registered")
    return True

def test_templates():
    r = client.get(f"{BASE}/templates")
    templates = r.json().get("templates", [])
    print(f"Total templates: {len(templates)}")
    new_protos = {"dlt645", "cjt188", "custom_tcp", "custom_udp", "s7plus"}
    new_templates = [t for t in templates if t["protocol"] in new_protos]
    print(f"New protocol templates: {len(new_templates)}")
    for t in new_templates:
        print(f"  - {t['id']}: {t['name']} ({t['protocol']})")
    if len(new_templates) < 5:
        print("FAIL: Expected at least 5 new templates")
        return False
    print("PASS: New templates available")
    return True

def test_device_clone():
    r = client.post(f"{BASE}/devices/quick-create", json={
        "template_id": "dlt645-single-phase-meter",
        "name": "Test DLT645 Meter",
        "id": "test-dlt645-clone",
    })
    if r.status_code != 200:
        print(f"FAIL: Could not create device: {r.status_code} {r.text}")
        return False
    print(f"Created device: {r.json().get('id', 'unknown')}")

    r = client.post(f"{BASE}/devices/test-dlt645-clone/clone", json={
        "new_id": "test-dlt645-cloned",
        "new_name": "Cloned Meter",
    })
    if r.status_code != 200:
        print(f"FAIL: Clone failed: {r.status_code} {r.text}")
        return False
    cloned = r.json()
    print(f"Cloned device: {cloned.get('id', 'unknown')} from {cloned.get('cloned_from', 'unknown')}")
    print("PASS: Device clone API")
    return True

def test_forward_presets():
    r = client.get(f"{BASE}/forward/presets")
    presets = r.json().get("presets", [])
    print(f"Forward presets: {len(presets)}")
    for p in presets:
        print(f"  - {p['id']}: {p['name']}")
    if len(presets) < 5:
        print("FAIL: Expected at least 5 presets")
        return False
    print("PASS: Forward presets API")
    return True

def test_rule_chains():
    r = client.get(f"{BASE}/rule-chains/templates")
    templates = r.json().get("templates", [])
    print(f"Rule chain templates: {len(templates)}")
    for t in templates:
        print(f"  - {t['id']}: {t['name']}")

    chain = {
        "id": "test-chain-1",
        "name": "Test Chain",
        "description": "Test rule chain",
        "nodes": [
            {"id": "n1", "type": "source", "config": {"device_id": "test-dlt645-clone", "point": "voltage_a"}},
            {"id": "n2", "type": "filter", "config": {"operator": ">", "value": 200}},
            {"id": "n3", "type": "sink", "config": {"sink_type": "log"}},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
        ],
        "enabled": False,
        "trigger_interval": 1.0,
    }
    r = client.post(f"{BASE}/rule-chains", json=chain)
    if r.status_code != 200:
        print(f"FAIL: Create chain failed: {r.status_code} {r.text}")
        return False
    print(f"Created chain: {r.json().get('id', 'unknown')}")

    r = client.get(f"{BASE}/rule-chains")
    chains = r.json().get("chains", [])
    print(f"Total chains: {len(chains)}")

    r = client.get(f"{BASE}/rule-chains/test-chain-1")
    if r.status_code != 200:
        print(f"FAIL: Get chain failed: {r.status_code}")
        return False
    print(f"Retrieved chain: {r.json().get('id', 'unknown')}")

    r = client.delete(f"{BASE}/rule-chains/test-chain-1")
    if r.status_code != 200:
        print(f"FAIL: Delete chain failed: {r.status_code}")
        return False
    print("PASS: Rule chain API")
    return True

def test_scenario_clone():
    scenario = {
        "id": "test-scenario-clone-src",
        "name": "Test Scenario",
        "description": "Test scenario for cloning",
        "devices": [],
        "rules": [],
    }
    r = client.post(f"{BASE}/scenarios", json=scenario)
    if r.status_code != 200:
        print(f"FAIL: Create scenario failed: {r.status_code} {r.text}")
        return False

    r = client.post(f"{BASE}/scenarios/test-scenario-clone-src/clone", json={
        "new_id": "test-scenario-cloned",
        "new_name": "Cloned Scenario",
    })
    if r.status_code != 200:
        print(f"FAIL: Clone scenario failed: {r.status_code} {r.text}")
        return False
    print(f"Cloned scenario: {r.json().get('id', 'unknown')}")
    print("PASS: Scenario clone API")
    return True

def cleanup():
    for device_id in ["test-dlt645-clone", "test-dlt645-cloned"]:
        try:
            client.delete(f"{BASE}/devices/{device_id}")
        except Exception:
            pass
    for scenario_id in ["test-scenario-clone-src", "test-scenario-cloned"]:
        try:
            client.delete(f"{BASE}/scenarios/{scenario_id}")
        except Exception:
            pass

if __name__ == "__main__":
    for i in range(15):
        try:
            client.get(f"{BASE}/protocols")
            break
        except Exception:
            print(f"Waiting for server... ({i+1}/15)")
            time.sleep(2)
    else:
        print("FAIL: Server not responding")
        sys.exit(1)

    results = []
    print("\n=== Test 1: Protocols ===")
    results.append(test_protocols())
    print("\n=== Test 2: Templates ===")
    results.append(test_templates())
    print("\n=== Test 3: Device Clone ===")
    results.append(test_device_clone())
    print("\n=== Test 4: Forward Presets ===")
    results.append(test_forward_presets())
    print("\n=== Test 5: Rule Chains ===")
    results.append(test_rule_chains())
    print("\n=== Test 6: Scenario Clone ===")
    results.append(test_scenario_clone())

    print("\n=== Cleanup ===")
    cleanup()

    print(f"\n=== Results: {sum(results)}/{len(results)} passed ===")
    if all(results):
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED!")
    sys.exit(0 if all(results) else 1)
