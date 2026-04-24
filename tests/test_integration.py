import pytest

from protoforge.core.integration import import_edgelite_config, import_pygbsentry_config
from protoforge.core.testing import TestCase, TestStep, TestRunner, TestStatus


def test_import_edgelite_single_device():
    config = {
        "devices": [
            {
                "id": "edge-001",
                "name": "Edge Sensor",
                "protocol": "modbus_tcp",
                "points": [
                    {
                        "name": "temperature",
                        "address": "0",
                        "data_type": "float32",
                        "generator_type": "random",
                        "min_value": 15.0,
                        "max_value": 35.0,
                    }
                ],
            }
        ]
    }
    devices = import_edgelite_config(config)
    assert len(devices) == 1
    assert devices[0].id == "edge-001"
    assert devices[0].protocol == "modbus_tcp"
    assert len(devices[0].points) == 1


def test_import_edgelite_string_input():
    import json
    config = json.dumps({
        "devices": [{"id": "edge-002", "name": "Test", "protocol": "http", "points": []}]
    })
    devices = import_edgelite_config(config)
    assert len(devices) == 1
    assert devices[0].id == "edge-002"


def test_import_pygbsentry():
    config = {
        "sip_servers": ["192.168.1.100"],
        "cameras": [
            {
                "device_id": "34020000001320000001",
                "name": "Front Camera",
                "sip_server": "192.168.1.100",
                "sip_port": 5060,
            }
        ],
    }
    devices = import_pygbsentry_config(config)
    assert len(devices) == 1
    assert devices[0].id == "34020000001320000001"
    assert devices[0].protocol == "gb28181"
    assert len(devices[0].points) >= 2


def test_test_runner_create_case():
    runner = TestRunner()
    tc = runner.create_test_case(
        "Test 1",
        "A test case",
        steps=[
            {"name": "Step 1", "action": "create_device", "params": {"id": "t1"}},
        ],
    )
    assert tc.name == "Test 1"
    assert len(tc.steps) == 1
    assert tc.steps[0].action == "create_device"


@pytest.mark.asyncio
async def test_test_runner_run():
    runner = TestRunner()
    tc = TestCase(id="tc-1", name="Test", steps=[
        TestStep(name="step1", action="list_devices", params={}, expected={}),
    ])
    result = await runner.run_test(tc)
    assert result.status == TestStatus.PASSED


@pytest.mark.asyncio
async def test_test_runner_suite():
    runner = TestRunner()
    tc1 = TestCase(id="tc-1", name="Test 1", steps=[
        TestStep(name="step1", action="list_devices"),
    ])
    tc2 = TestCase(id="tc-2", name="Test 2", steps=[
        TestStep(name="step1", action="list_devices"),
    ])
    report = await runner.run_test_suite("Suite", [tc1, tc2])
    assert report.total == 2
    assert report.passed == 2
    assert report.success_rate == 100.0


def test_test_report_to_dict():
    from protoforge.core.testing import TestReport
    report = TestReport(id="r1", name="Test", total=5, passed=3, failed=1, errors=1)
    d = report.to_dict()
    assert d["total"] == 5
    assert d["passed"] == 3
    assert d["success_rate"] == 60.0
