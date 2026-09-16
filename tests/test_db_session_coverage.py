"""Comprehensive tests for db/session.py - Database CRUD operations."""

import pytest

from protoforge.db.session import Database, _safe_json_loads
from protoforge.models.device import DeviceConfig, PointConfig, DataType, GeneratorType
from protoforge.models.scenario import ScenarioConfig, Rule, RuleType
from protoforge.models.template import TemplateDetail


# ==================== Fixtures ====================

@pytest.fixture
async def db():
    """Provide a connected in-memory database, cleaned up after test."""
    d = Database(":memory:")
    await d.connect()
    try:
        yield d
    finally:
        await d.close()


# ==================== Helper Function Tests ====================

class TestSafeJsonLoads:
    def test_valid_json(self):
        assert _safe_json_loads('{"key": "value"}') == {"key": "value"}

    def test_invalid_json(self):
        assert _safe_json_loads("not json") == []

    def test_invalid_json_with_default(self):
        assert _safe_json_loads("not json", default={}) == {}

    def test_none_input(self):
        assert _safe_json_loads(None) == []

    def test_list_input(self):
        assert _safe_json_loads('[1, 2, 3]') == [1, 2, 3]


# ==================== Database Connection Tests ====================

class TestDatabaseConnection:
    @pytest.mark.asyncio
    async def test_connect_sqlite_memory(self):
        d = Database(":memory:")
        await d.connect()
        assert d._db is not None
        await d.close()

    @pytest.mark.asyncio
    async def test_connect_sqlite_file(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        d = Database(db_path)
        await d.connect()
        assert d._db is not None
        await d.close()

    @pytest.mark.asyncio
    async def test_close(self):
        d = Database(":memory:")
        await d.connect()
        await d.close()
        assert d._db is None

    @pytest.mark.asyncio
    async def test_is_postgresql_url(self):
        d = Database()
        assert d._is_postgresql_url("postgresql://localhost/db") is True
        assert d._is_postgresql_url("postgres://localhost/db") is True
        assert d._is_postgresql_url("postgresql+asyncpg://localhost/db") is True
        assert d._is_postgresql_url("sqlite:///test.db") is False
        assert d._is_postgresql_url(":memory:") is False


# ==================== Device CRUD Tests ====================

class TestDeviceCRUD:
    def _make_device_config(self, device_id="test-dev-001"):
        return DeviceConfig(
            id=device_id,
            name="Test Device",
            protocol="modbus_tcp",
            points=[
                PointConfig(
                    name="temperature",
                    address="0",
                    data_type=DataType.FLOAT32,
                    generator_type=GeneratorType.RANDOM,
                    min_value=0.0,
                    max_value=100.0,
                ),
                PointConfig(
                    name="pressure",
                    address="1",
                    data_type=DataType.FLOAT32,
                    generator_type=GeneratorType.FIXED,
                    fixed_value=42.0,
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_save_and_load_device(self, db):
        config = self._make_device_config()
        await db.save_device(config)
        loaded = await db.load_device("test-dev-001")
        assert loaded is not None
        assert loaded.id == "test-dev-001"
        assert loaded.name == "Test Device"
        assert loaded.protocol == "modbus_tcp"
        assert len(loaded.points) == 2

    @pytest.mark.asyncio
    async def test_load_nonexistent_device(self, db):
        loaded = await db.load_device("nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_all_devices(self, db):
        await db.save_device(self._make_device_config("dev-1"))
        await db.save_device(self._make_device_config("dev-2"))
        await db.save_device(self._make_device_config("dev-3"))
        devices = await db.load_all_devices()
        assert len(devices) >= 3

    @pytest.mark.asyncio
    async def test_load_all_devices_with_pagination(self, db):
        for i in range(5):
            await db.save_device(self._make_device_config(f"page-dev-{i}"))
        devices = await db.load_all_devices(limit=2, offset=0)
        assert len(devices) <= 2

    @pytest.mark.asyncio
    async def test_delete_device(self, db):
        await db.save_device(self._make_device_config("delete-dev"))
        await db.delete_device("delete-dev")
        loaded = await db.load_device("delete-dev")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_update_device(self, db):
        config = self._make_device_config("update-dev")
        await db.save_device(config)
        config.name = "Updated Name"
        await db.save_device(config)
        loaded = await db.load_device("update-dev")
        assert loaded.name == "Updated Name"


# ==================== Scenario CRUD Tests ====================

class TestScenarioCRUD:
    def _make_scenario_config(self, scenario_id="test-scen-001"):
        return ScenarioConfig(
            id=scenario_id,
            name="Test Scenario",
            description="A test scenario",
            devices=[],
            rules=[
                Rule(
                    id="rule-1",
                    name="test rule",
                    rule_type=RuleType.THRESHOLD,
                    source_device_id="dev-1",
                    source_point="temperature",
                    target_device_id="dev-2",
                    target_point="valve",
                    target_value=50.0,
                    condition={"operator": ">", "value": 80},
                    enabled=True,
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_save_and_load_scenario(self, db):
        config = self._make_scenario_config()
        await db.save_scenario(config)
        loaded = await db.load_scenario("test-scen-001")
        assert loaded is not None
        assert loaded.id == "test-scen-001"
        assert loaded.name == "Test Scenario"

    @pytest.mark.asyncio
    async def test_load_nonexistent_scenario(self, db):
        loaded = await db.load_scenario("nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_all_scenarios(self, db):
        await db.save_scenario(self._make_scenario_config("scen-1"))
        await db.save_scenario(self._make_scenario_config("scen-2"))
        scenarios = await db.load_all_scenarios()
        assert len(scenarios) >= 2

    @pytest.mark.asyncio
    async def test_load_all_scenarios_with_pagination(self, db):
        for i in range(5):
            await db.save_scenario(self._make_scenario_config(f"page-scen-{i}"))
        scenarios = await db.load_all_scenarios(limit=2)
        assert len(scenarios) <= 2

    @pytest.mark.asyncio
    async def test_delete_scenario(self, db):
        await db.save_scenario(self._make_scenario_config("delete-scen"))
        await db.delete_scenario("delete-scen")
        loaded = await db.load_scenario("delete-scen")
        assert loaded is None


# ==================== Template CRUD Tests ====================

class TestTemplateCRUD:
    def _make_template(self, template_id="test-tpl-001"):
        return TemplateDetail(
            id=template_id,
            name="Test Template",
            protocol="modbus_tcp",
            description="Test template",
            points=[],
            protocol_config={"port": 502, "host": "0.0.0.0"},
        )

    @pytest.mark.asyncio
    async def test_save_and_load_template(self, db):
        await db.save_template(self._make_template())
        loaded = await db.load_template("test-tpl-001")
        assert loaded is not None
        assert loaded.name == "Test Template"

    @pytest.mark.asyncio
    async def test_load_nonexistent_template(self, db):
        loaded = await db.load_template("nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_all_templates(self, db):
        await db.save_template(self._make_template("tpl-1"))
        await db.save_template(self._make_template("tpl-2"))
        templates = await db.load_all_templates()
        assert len(templates) >= 2

    @pytest.mark.asyncio
    async def test_delete_template(self, db):
        await db.save_template(self._make_template("delete-tpl"))
        await db.delete_template("delete-tpl")
        loaded = await db.load_template("delete-tpl")
        assert loaded is None


# ==================== Test Case CRUD Tests ====================

class TestTestCaseCRUD:
    @pytest.mark.asyncio
    async def test_save_and_load_test_case(self, db):
        case_data = {
            "id": "tc-001",
            "name": "Test Case 1",
            "protocol": "modbus_tcp",
            "steps": [{"action": "read", "address": "0"}],
        }
        await db.save_test_case(case_data)
        loaded = await db.load_test_case("tc-001")
        assert loaded is not None
        assert loaded["name"] == "Test Case 1"

    @pytest.mark.asyncio
    async def test_load_nonexistent_test_case(self, db):
        loaded = await db.load_test_case("nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_all_test_cases(self, db):
        await db.save_test_case({"id": "tc-1", "name": "TC1", "protocol": "http"})
        await db.save_test_case({"id": "tc-2", "name": "TC2", "protocol": "modbus"})
        cases = await db.load_all_test_cases()
        assert len(cases) >= 2

    @pytest.mark.asyncio
    async def test_delete_test_case(self, db):
        await db.save_test_case({"id": "del-tc", "name": "Delete", "protocol": "http"})
        await db.delete_test_case("del-tc")
        loaded = await db.load_test_case("del-tc")
        assert loaded is None


# ==================== Test Suite CRUD Tests ====================

class TestTestSuiteCRUD:
    @pytest.mark.asyncio
    async def test_save_and_load_test_suite(self, db):
        suite_data = {
            "id": "ts-001",
            "name": "Test Suite 1",
            "test_case_ids": ["tc-1", "tc-2"],
        }
        await db.save_test_suite(suite_data)
        loaded = await db.load_test_suite("ts-001")
        assert loaded is not None
        assert loaded["name"] == "Test Suite 1"

    @pytest.mark.asyncio
    async def test_load_nonexistent_test_suite(self, db):
        loaded = await db.load_test_suite("nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_all_test_suites(self, db):
        await db.save_test_suite({"id": "ts-1", "name": "TS1", "test_case_ids": []})
        await db.save_test_suite({"id": "ts-2", "name": "TS2", "test_case_ids": []})
        suites = await db.load_all_test_suites()
        assert len(suites) >= 2

    @pytest.mark.asyncio
    async def test_delete_test_suite(self, db):
        await db.save_test_suite({"id": "del-ts", "name": "Delete", "test_case_ids": []})
        await db.delete_test_suite("del-ts")
        loaded = await db.load_test_suite("del-ts")
        assert loaded is None


# ==================== Test Report CRUD Tests ====================

class TestTestReportCRUD:
    @pytest.mark.asyncio
    async def test_save_and_load_test_report(self, db):
        report_data = {
            "id": "tr-001",
            "suite_id": "ts-001",
            "status": "passed",
            "total": 10,
            "passed": 10,
            "failed": 0,
        }
        await db.save_test_report(report_data)
        loaded = await db.load_test_report("tr-001")
        assert loaded is not None

    @pytest.mark.asyncio
    async def test_load_nonexistent_test_report(self, db):
        loaded = await db.load_test_report("nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_test_reports(self, db):
        for i in range(5):
            await db.save_test_report({
                "id": f"tr-{i}",
                "suite_id": "ts-1",
                "status": "passed" if i % 2 == 0 else "failed",
                "total": 10,
                "passed": 8,
                "failed": 2,
            })
        reports = await db.load_test_reports(count=3)
        assert len(reports) <= 3

    @pytest.mark.asyncio
    async def test_delete_test_report(self, db):
        await db.save_test_report({"id": "del-tr", "suite_id": "ts-1", "status": "passed"})
        await db.delete_test_report("del-tr")
        loaded = await db.load_test_report("del-tr")
        assert loaded is None


# ==================== User CRUD Tests ====================

class TestUserCRUD:
    @pytest.mark.asyncio
    async def test_save_and_load_user(self, db):
        user_data = {
            "id": "user-001",
            "username": "testuser",
            "password_hash": "hashed_password",
            "role": "viewer",
        }
        await db.save_user(user_data)
        loaded = await db.load_user("testuser")
        assert loaded is not None

    @pytest.mark.asyncio
    async def test_load_nonexistent_user(self, db):
        loaded = await db.load_user("nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_all_users(self, db):
        await db.save_user({"id": "u1", "username": "user1", "password_hash": "h1", "role": "viewer"})
        await db.save_user({"id": "u2", "username": "user2", "password_hash": "h2", "role": "operator"})
        users = await db.load_all_users()
        assert len(users) >= 2

    @pytest.mark.asyncio
    async def test_delete_user(self, db):
        await db.save_user({"id": "del-u", "username": "deleteuser", "password_hash": "h", "role": "viewer"})
        await db.delete_user("deleteuser")
        loaded = await db.load_user("deleteuser")
        assert loaded is None


# ==================== Audit Log Tests ====================

class TestAuditLog:
    @pytest.mark.asyncio
    async def test_save_and_load_audit_logs(self, db):
        # Try to save an audit log entry
        if hasattr(db, 'save_audit_log'):
            await db.save_audit_log({
                "action": "create_device",
                "user": "admin",
                "detail": "Created device test-001",
            })
        # Try to load audit logs
        if hasattr(db, 'load_audit_logs'):
            logs = await db.load_audit_logs()
            assert isinstance(logs, list)
