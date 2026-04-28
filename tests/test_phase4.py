import os

import pytest
import pytest_asyncio

os.environ["PROTOFORGE_NO_AUTH"] = "1"

from httpx import ASGITransport, AsyncClient

from protoforge.core.engine import SimulationEngine
from protoforge.core.log_bus import LogBus
from protoforge.core.template import TemplateManager
from protoforge.core.testing import (
    AssertionEngine, Assertion, AssertionType, VariableStore,
    TestCase, TestStep, TestSuite, TestRunner, TestStatus,
)
from protoforge.protocols.http.server import HttpSimulatorServer
from protoforge.protocols.modbus.server import ModbusTcpServer
from protoforge.protocols.modbus.rtu_server import ModbusRtuServer
from protoforge.protocols.bacnet.server import BACnetServer
from protoforge.protocols.s7.server import S7Server
import protoforge.main as main_module


@pytest_asyncio.fixture
async def client():
    main_module._log_bus = LogBus()
    main_module._template_manager = TemplateManager()
    main_module._template_manager.load_builtin_templates()

    from protoforge.db.session import Database
    main_module._database = Database()
    await main_module._database.connect()

    main_module._engine = SimulationEngine()
    main_module._engine.register_protocol(ModbusTcpServer())
    main_module._engine.register_protocol(ModbusRtuServer())
    main_module._engine.register_protocol(HttpSimulatorServer())
    main_module._engine.register_protocol(BACnetServer())
    main_module._engine.register_protocol(S7Server())
    await main_module._engine.start()

    transport = ASGITransport(app=main_module.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await main_module._engine.stop()
    await main_module._database.close()
    main_module._engine = None
    main_module._template_manager = None
    main_module._database = None
    main_module._log_bus = None


class TestAssertionEngine:
    def test_equals_pass(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.EQUALS, expected="hello")
        result = engine.evaluate("hello", a)
        assert result["passed"]

    def test_equals_fail(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.EQUALS, expected="hello")
        result = engine.evaluate("world", a)
        assert not result["passed"]

    def test_contains(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.CONTAINS, expected="world")
        result = engine.evaluate("hello world", a)
        assert result["passed"]

    def test_not_contains(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.NOT_CONTAINS, expected="xyz")
        result = engine.evaluate("hello world", a)
        assert result["passed"]

    def test_greater_than(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.GREATER_THAN, expected=5)
        result = engine.evaluate(10, a)
        assert result["passed"]

    def test_less_than(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.LESS_THAN, expected=100)
        result = engine.evaluate(50, a)
        assert result["passed"]

    def test_regex_match(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.REGEX_MATCH, expected=r"^\d+$")
        result = engine.evaluate("12345", a)
        assert result["passed"]

    def test_json_path(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.JSON_PATH, json_path="name", expected="test")
        result = engine.evaluate({"name": "test", "value": 42}, a)
        assert result["passed"]

    def test_not_null(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.NOT_NULL, target="id")
        result = engine.evaluate({"id": "abc"}, a)
        assert result["passed"]

    def test_type_check(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.TYPE_CHECK, expected="list")
        result = engine.evaluate([1, 2, 3], a)
        assert result["passed"]

    def test_status_code(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.STATUS_CODE, expected=200)
        result = engine.evaluate({"status_code": 200, "data": "ok"}, a)
        assert result["passed"]

    def test_length_equals(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.LENGTH_EQUALS, expected=3)
        result = engine.evaluate([1, 2, 3], a)
        assert result["passed"]

    def test_length_greater(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.LENGTH_GREATER, expected=2)
        result = engine.evaluate([1, 2, 3], a)
        assert result["passed"]

    def test_target_resolution(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.EQUALS, target="status", expected="ok")
        result = engine.evaluate({"status": "ok", "data": 123}, a)
        assert result["passed"]

    def test_custom_message(self):
        engine = AssertionEngine()
        a = Assertion(type=AssertionType.EQUALS, expected="a", message="值检查")
        result = engine.evaluate("b", a)
        assert "值检查" in result["message"]


class TestVariableStore:
    def test_set_and_get(self):
        store = VariableStore()
        store.set("key1", "value1")
        assert store.get("key1") == "value1"

    def test_resolve_variable(self):
        store = VariableStore()
        store.set("device_id", "dev-001")
        resolved = store.resolve("${device_id}")
        assert resolved == "dev-001"

    def test_resolve_dict(self):
        store = VariableStore()
        store.set("id", "test-1")
        result = store.resolve({"device_id": "${id}", "name": "fixed"})
        assert result["device_id"] == "test-1"
        assert result["name"] == "fixed"

    def test_resolve_list(self):
        store = VariableStore()
        store.set("val", 42)
        result = store.resolve(["${val}", "static"])
        assert result[0] == 42
        assert result[1] == "static"

    def test_clear(self):
        store = VariableStore()
        store.set("k", "v")
        store.clear()
        assert store.get("k") is None


class TestTestCaseCRUD:
    async def test_save_and_get(self):
        runner = TestRunner()
        tc = TestCase(id="tc-1", name="Test 1", steps=[
            TestStep(name="Step 1", action="list_devices")
        ])
        await runner.save_test_case(tc)
        assert runner.get_test_case("tc-1") is not None
        assert runner.get_test_case("tc-1").name == "Test 1"

    async def test_list_cases(self):
        runner = TestRunner()
        await runner.save_test_case(TestCase(id="tc-1", name="A", tags=["smoke"]))
        await runner.save_test_case(TestCase(id="tc-2", name="B", tags=["regression"]))
        await runner.save_test_case(TestCase(id="tc-3", name="C", tags=["smoke"]))
        assert len(runner.list_test_cases()) == 3
        assert len(runner.list_test_cases(tag="smoke")) == 2

    async def test_delete_case(self):
        runner = TestRunner()
        await runner.save_test_case(TestCase(id="tc-1", name="A"))
        assert await runner.delete_test_case("tc-1")
        assert runner.get_test_case("tc-1") is None
        assert not await runner.delete_test_case("nonexistent")

    def test_from_dict(self):
        data = {
            "id": "tc-x",
            "name": "From Dict",
            "tags": ["auto"],
            "steps": [
                {"name": "Step1", "action": "list_devices",
                 "assertions": [{"type": "not_null", "target": ""}],
                 "extract": {"count": "length"}}
            ]
        }
        tc = TestCase.from_dict(data)
        assert tc.id == "tc-x"
        assert len(tc.steps) == 1
        assert len(tc.steps[0].assertions) == 1
        assert tc.steps[0].extract == {"count": "length"}

    def test_to_dict_roundtrip(self):
        tc = TestCase(id="tc-r", name="Roundtrip", tags=["test"], steps=[
            TestStep(name="S1", action="wait", params={"seconds": 0.1})
        ])
        d = tc.to_dict()
        tc2 = TestCase.from_dict(d)
        assert tc2.id == tc.id
        assert tc2.name == tc.name
        assert len(tc2.steps) == 1


class TestTestSuite:
    async def test_suite_crud(self):
        runner = TestRunner()
        suite = TestSuite(id="s-1", name="Suite 1", test_case_ids=["tc-1", "tc-2"])
        await runner.save_test_suite(suite)
        assert runner.get_test_suite("s-1") is not None
        assert len(runner.list_test_suites()) == 1
        assert await runner.delete_test_suite("s-1")
        assert runner.get_test_suite("s-1") is None


class TestTestReportHTML:
    def test_report_html_generation(self):
        runner = TestRunner()
        tc = TestCase(id="tc-1", name="HTML Test", steps=[
            TestStep(name="Step1", action="list_devices",
                     status=TestStatus.PASSED, duration=0.1)
        ])
        tc.status = TestStatus.PASSED
        tc.start_time = 1000.0
        tc.end_time = 1001.0

        from protoforge.core.testing import TestReport
        report = TestReport(id="r-1", name="HTML Report", test_cases=[tc],
                            start_time=1000.0, end_time=1001.0, total=1, passed=1)
        html = report.to_html()
        assert "<html" in html
        assert "HTML Test" in html
        assert "PASSED" in html

    def test_report_trend(self):
        runner = TestRunner()
        from protoforge.core.testing import TestReport
        for i in range(3):
            report = TestReport(id=f"r-{i}", name=f"Report {i}",
                                start_time=1000.0 + i, end_time=1001.0 + i,
                                total=1, passed=1)
            runner._reports.append(report)
        trend = runner.get_report_trend(count=2)
        assert len(trend) == 2


@pytest.mark.asyncio
async def test_test_case_api_crud(client):
    case_def = {
        "id": "api-tc-001",
        "name": "API Test Case",
        "description": "Created via API",
        "tags": ["api", "smoke"],
        "steps": [
            {"name": "List devices", "action": "list_devices",
             "assertions": [{"type": "not_null", "target": ""}]}
        ]
    }
    response = await client.post("/api/v1/tests/cases", json=case_def)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "api-tc-001"
    assert data["name"] == "API Test Case"

    response = await client.get("/api/v1/tests/cases")
    assert response.status_code == 200
    cases = response.json()
    assert any(c["id"] == "api-tc-001" for c in cases)

    response = await client.get("/api/v1/tests/cases/api-tc-001")
    assert response.status_code == 200
    assert response.json()["name"] == "API Test Case"

    response = await client.delete("/api/v1/tests/cases/api-tc-001")
    assert response.status_code == 200

    response = await client.get("/api/v1/tests/cases/api-tc-001")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_test_suite_api(client):
    suite_def = {
        "id": "api-suite-001",
        "name": "API Test Suite",
        "description": "Created via API",
        "test_case_ids": [],
        "tags": ["api"],
    }
    response = await client.post("/api/v1/tests/suites", json=suite_def)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "api-suite-001"

    response = await client.get("/api/v1/tests/suites")
    assert response.status_code == 200
    suites = response.json()
    assert any(s["id"] == "api-suite-001" for s in suites)

    response = await client.delete("/api/v1/tests/suites/api-suite-001")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_run_test_with_assertions(client):
    test_cases = [{
        "id": "assert-tc-001",
        "name": "Assertion Test",
        "steps": [
            {
                "name": "Create device",
                "action": "create_device",
                "params": {"id": "assert-dev", "name": "AssertDev", "protocol": "http",
                           "points": [{"name": "v", "address": "0", "data_type": "float32",
                                       "generator_type": "random", "min_value": 0, "max_value": 100}]},
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "not_null", "target": "id"}
                ]
            },
            {
                "name": "Read points",
                "action": "read_points",
                "params": {"device_id": "assert-dev"},
                "assertions": [
                    {"type": "length_greater", "expected": 0, "message": "测点列表不应为空"}
                ]
            },
            {
                "name": "Delete device",
                "action": "delete_device",
                "params": {"device_id": "assert-dev"}
            }
        ]
    }]
    response = await client.post("/api/v1/tests/run", json=test_cases)
    assert response.status_code == 200
    report = response.json()
    assert report["total"] == 1
    assert report["passed"] == 1


@pytest.mark.asyncio
async def test_report_html_endpoint(client):
    test_cases = [{
        "id": "html-tc-001",
        "name": "HTML Report Test",
        "steps": [
            {"name": "List devices", "action": "list_devices"}
        ]
    }]
    response = await client.post("/api/v1/tests/run", json=test_cases)
    report = response.json()
    report_id = report["id"]

    response = await client.get(f"/api/v1/tests/reports/{report_id}/html")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_report_trend_endpoint(client):
    test_cases = [{
        "id": "trend-tc-001",
        "name": "Trend Test",
        "steps": [{"name": "List devices", "action": "list_devices"}]
    }]
    await client.post("/api/v1/tests/run", json=test_cases)

    response = await client.get("/api/v1/tests/reports/trend")
    assert response.status_code == 200
    trend = response.json()
    assert isinstance(trend, list)
    assert len(trend) > 0


@pytest.mark.asyncio
async def test_run_case_by_id(client):
    case_def = {
        "id": "run-by-id-001",
        "name": "Run By ID Test",
        "steps": [
            {"name": "List devices", "action": "list_devices"}
        ]
    }
    await client.post("/api/v1/tests/cases", json=case_def)

    response = await client.post("/api/v1/tests/run/case/run-by-id-001")
    assert response.status_code == 200
    report = response.json()
    assert report["total"] == 1

    await client.delete("/api/v1/tests/cases/run-by-id-001")


@pytest.mark.asyncio
async def test_variable_extraction(client):
    test_cases = [{
        "id": "var-tc-001",
        "name": "Variable Extraction Test",
        "steps": [
            {
                "name": "Create device",
                "action": "create_device",
                "params": {"id": "var-dev", "name": "VarDev", "protocol": "http", "points": []},
                "extract": {"device_name": "name", "device_protocol": "protocol"}
            },
            {
                "name": "Delete device",
                "action": "delete_device",
                "params": {"device_id": "var-dev"}
            }
        ]
    }]
    response = await client.post("/api/v1/tests/run", json=test_cases)
    assert response.status_code == 200
    report = response.json()
    tc = report["test_cases"][0]
    create_step = tc["steps"][0]
    assert "device_name" in create_step.get("extracted_vars", {})
    assert create_step["extracted_vars"]["device_name"] == "VarDev"


@pytest.mark.asyncio
async def test_step_skip_and_delay(client):
    test_cases = [{
        "id": "skip-tc-001",
        "name": "Skip and Delay Test",
        "steps": [
            {"name": "Skipped step", "action": "list_devices", "skip": True},
            {"name": "Wait step", "action": "wait", "params": {"seconds": 0.1}},
            {"name": "Normal step", "action": "list_devices"}
        ]
    }]
    response = await client.post("/api/v1/tests/run", json=test_cases)
    assert response.status_code == 200
    report = response.json()
    steps = report["test_cases"][0]["steps"]
    assert steps[0]["status"] == "skipped"
    assert steps[1]["status"] == "passed"
    assert steps[2]["status"] == "passed"
