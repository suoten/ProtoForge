import pytest

from protoforge.core.testing import TestCase, TestStep, TestRunner, TestStatus


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


def test_edgelite_protocol_mapping():
    from protoforge.core.edgelite import PROTOCOL_MAP, DATA_TYPE_MAP, ACCESS_MODE_MAP
    assert PROTOCOL_MAP["modbus_tcp"] == "modbus_tcp"
    assert PROTOCOL_MAP["ab"] == "allen_bradley"
    assert PROTOCOL_MAP["opcda"] == "opc_da"
    assert DATA_TYPE_MAP["float32"] == "float32"
    assert "float64" in DATA_TYPE_MAP
    assert ACCESS_MODE_MAP["ro"] == "r"
    assert ACCESS_MODE_MAP["wo"] == "w"


def test_edgelite_push_fields():
    from protoforge.core.edgelite import EDGELITE_PUSH_FIELDS
    assert len(EDGELITE_PUSH_FIELDS) >= 3
    keys = [f["key"] for f in EDGELITE_PUSH_FIELDS]
    assert "edgelite_url" in keys
    assert "edgelite_username" in keys
    assert "edgelite_password" in keys


def test_edgelite_convert_device():
    from protoforge.core.edgelite import convert_device_to_edgelite
    from dataclasses import dataclass, field

    @dataclass
    class FakeDevice:
        id: str = "test-001"
        name: str = "Test PLC"
        protocol: str = "modbus_tcp"
        protocol_config: dict = field(default_factory=lambda: {"host": "192.168.1.100", "port": 5020, "slave_id": 1})
        points: list = field(default_factory=lambda: [
            {"name": "temp", "data_type": "float32", "address": "100", "access": "rw", "unit": "C"}
        ])

    result = convert_device_to_edgelite(FakeDevice(), "192.168.1.100")
    assert result is not None
    assert result["device_id"] == "test-001"
    assert result["protocol"] == "modbus_tcp"
    assert result["config"]["host"] == "192.168.1.100"
    assert result["config"]["slave_id"] == 1
    assert len(result["points"]) == 1
    assert result["points"][0]["name"] == "temp"


def test_edgelite_convert_gb28181_skipped():
    from protoforge.core.edgelite import convert_device_to_edgelite
    from dataclasses import dataclass

    @dataclass
    class FakeDevice:
        id: str = "cam-001"
        name: str = "Camera"
        protocol: str = "gb28181"
        protocol_config: dict = None
        points: list = None

    result = convert_device_to_edgelite(FakeDevice())
    assert result is None
