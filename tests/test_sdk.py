"""Tests for ProtoForge SDK (sync and async clients)."""

import httpx
import pytest

from protoforge.sdk import AsyncProtoForgeClient, ProtoForgeClient


def _mock_handler(request: httpx.Request) -> httpx.Response:
    """Mock HTTP handler that returns appropriate responses based on the request."""
    method = request.method
    path = request.url.path.replace("/api/v1", "")

    # Health endpoint
    if path == "/health":
        return httpx.Response(200, json={"status": "ok"})

    # Protocols
    if path == "/protocols" and method == "GET":
        return httpx.Response(200, json={"protocols": ["modbus_tcp", "http", "bacnet"]})
    if path == "/protocols/info":
        return httpx.Response(200, json={"protocols": [{"name": "modbus_tcp"}]})
    if path == "/protocols/modbus_tcp/config":
        return httpx.Response(200, json={"port": 502})
    if path == "/protocols/modbus_tcp/device-config":
        return httpx.Response(200, json={"template": "default"})
    if path == "/protocols/modbus_tcp/start" and method == "POST":
        return httpx.Response(200, json={"status": "started"})
    if path == "/protocols/modbus_tcp/stop" and method == "POST":
        return httpx.Response(200, json={"status": "stopped"})

    # Devices
    if path == "/devices" and method == "GET":
        return httpx.Response(200, json={"devices": [{"id": "dev1"}]})
    if path == "/devices" and method == "POST":
        return httpx.Response(200, json={"id": "dev1", "status": "created"})
    if path == "/devices/quick-create" and method == "POST":
        return httpx.Response(200, json={"id": "dev1", "status": "created"})
    if path == "/devices/batch" and method == "POST":
        return httpx.Response(200, json={"created": 2})
    if path == "/devices/batch/delete" and method == "POST":
        return httpx.Response(200, json={"deleted": 2})
    if path == "/devices/batch/start" and method == "POST":
        return httpx.Response(200, json={"started": 2})
    if path == "/devices/batch/stop" and method == "POST":
        return httpx.Response(200, json={"stopped": 2})
    if path == "/devices/dev1" and method == "GET":
        return httpx.Response(200, json={"id": "dev1", "name": "Test Device"})
    if path == "/devices/dev1" and method == "DELETE":
        return httpx.Response(200, json={"status": "deleted"})
    if path == "/devices/dev1" and method == "PUT":
        return httpx.Response(200, json={"id": "dev1", "updated": True})
    if path == "/devices/dev1/start" and method == "POST":
        return httpx.Response(200, json={"status": "started"})
    if path == "/devices/dev1/stop" and method == "POST":
        return httpx.Response(200, json={"status": "stopped"})
    if path == "/devices/dev1/points" and method == "GET":
        return httpx.Response(200, json={"points": [{"name": "temp"}]})
    if path == "/devices/dev1/points/temp" and method == "PUT":
        return httpx.Response(200, json={"ok": True})
    if path == "/devices/dev1/config" and method == "GET":
        return httpx.Response(200, json={"protocol": "modbus_tcp"})
    if path == "/devices/dev1/connection-guide" and method == "GET":
        return httpx.Response(200, json={"guide": "connect here"})

    # Templates
    if path == "/templates" and method == "GET":
        return httpx.Response(200, json={"templates": [{"id": "tpl1"}]})
    if path == "/templates" and method == "POST":
        return httpx.Response(200, json={"id": "tpl1"})
    if path == "/templates/tpl1" and method == "GET":
        return httpx.Response(200, json={"id": "tpl1", "name": "Test"})
    if path == "/templates/search":
        return httpx.Response(200, json={"templates": [{"id": "tpl1"}]})
    if path == "/templates/tags":
        return httpx.Response(200, json={"tags": ["modbus", "bacnet"]})
    if path == "/templates/tpl1/instantiate" and method == "POST":
        return httpx.Response(200, json={"id": "dev1", "status": "created"})

    # Scenarios
    if path == "/scenarios" and method == "GET":
        return httpx.Response(200, json={"scenarios": [{"id": "sc1"}]})
    if path == "/scenarios" and method == "POST":
        return httpx.Response(200, json={"id": "sc1"})
    if path == "/scenarios/sc1" and method == "GET":
        return httpx.Response(200, json={"id": "sc1", "name": "Test"})
    if path == "/scenarios/sc1" and method == "PUT":
        return httpx.Response(200, json={"id": "sc1", "updated": True})
    if path == "/scenarios/sc1" and method == "DELETE":
        return httpx.Response(200, json={"status": "deleted"})
    if path == "/scenarios/sc1/start":
        return httpx.Response(200, json={"status": "started"})
    if path == "/scenarios/sc1/stop":
        return httpx.Response(200, json={"status": "stopped"})
    if path == "/scenarios/sc1/export":
        return httpx.Response(200, json={"id": "sc1", "export": True})
    if path == "/scenarios/import" and method == "POST":
        return httpx.Response(200, json={"id": "sc1"})
    if path == "/scenarios/sc1/snapshot":
        return httpx.Response(200, json={"snapshot": {}})

    # Logs
    if path == "/logs" and method == "GET":
        return httpx.Response(200, json={"entries": [{"msg": "test"}]})
    if path == "/logs" and method == "DELETE":
        return httpx.Response(200, json={"status": "cleared"})

    # Tests
    if path == "/tests/cases" and method == "POST":
        return httpx.Response(200, json={"id": "case1"})
    if path == "/tests/cases" and method == "GET":
        return httpx.Response(200, json={"cases": [{"id": "case1"}]})
    if path == "/tests/cases/case1" and method == "GET":
        return httpx.Response(200, json={"id": "case1"})
    if path == "/tests/cases/case1" and method == "PUT":
        return httpx.Response(200, json={"id": "case1", "updated": True})
    if path == "/tests/cases/case1" and method == "DELETE":
        return httpx.Response(200, json={"status": "deleted"})
    if path == "/tests/suites" and method == "POST":
        return httpx.Response(200, json={"id": "suite1"})
    if path == "/tests/suites" and method == "GET":
        return httpx.Response(200, json={"suites": [{"id": "suite1"}]})
    if path == "/tests/suites/suite1" and method == "GET":
        return httpx.Response(200, json={"id": "suite1"})
    if path == "/tests/suites/suite1" and method == "DELETE":
        return httpx.Response(200, json={"status": "deleted"})
    if path == "/tests/run" and method == "POST":
        return httpx.Response(200, json={"results": []})
    if path == "/tests/run/case/case1":
        return httpx.Response(200, json={"result": "pass"})
    if path == "/tests/run/suite/suite1":
        return httpx.Response(200, json={"results": []})
    if path == "/tests/reports" and method == "GET":
        return httpx.Response(200, json={"reports": [{"id": "rep1"}]})
    if path == "/tests/reports/rep1" and method == "GET":
        return httpx.Response(200, json={"id": "rep1"})
    if path == "/tests/reports/rep1/html" and method == "GET":
        return httpx.Response(200, text="<html>report</html>")
    if path == "/tests/reports/trend":
        return httpx.Response(200, json={"trends": []})
    if path == "/tests/quick-test":
        return httpx.Response(200, json={"result": "ok"})
    if path == "/tests/suggestions":
        return httpx.Response(200, json={"suggestions": []})
    if path == "/tests/action-types":
        return httpx.Response(200, json={"action_types": []})
    if path == "/tests/assertion-types":
        return httpx.Response(200, json={"assertion_types": []})

    # Recorder
    if path == "/recorder/start":
        return httpx.Response(200, json={"id": "rec1"})
    if path == "/recorder/stop":
        return httpx.Response(200, json={"status": "stopped"})
    if path == "/recorder/recordings" and method == "GET":
        return httpx.Response(200, json={"recordings": [{"id": "rec1"}]})
    if path == "/recorder/recordings/rec1" and method == "GET":
        return httpx.Response(200, json={"id": "rec1"})
    if path == "/recorder/recordings/rec1" and method == "DELETE":
        return httpx.Response(200, json={"status": "deleted"})
    if path == "/recorder/recordings/rec1/export":
        return httpx.Response(200, json={"id": "rec1", "data": []})
    if path == "/recorder/recordings/rec1/replay":
        return httpx.Response(200, json={"status": "replaying"})
    if path == "/recorder/stats":
        return httpx.Response(200, json={"is_recording": False, "total_recordings": 0})

    # Settings
    if path == "/settings" and method == "GET":
        return httpx.Response(200, json={"key": "value"})
    if path == "/settings" and method == "PUT":
        return httpx.Response(200, json={"updated": True})

    # Auth
    if path == "/auth/login" and method == "POST":
        return httpx.Response(200, json={"access_token": "tok123", "token_type": "bearer"})
    if path == "/auth/refresh":
        return httpx.Response(200, json={"access_token": "tok456"})
    if path == "/auth/change-password":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/auth/register":
        return httpx.Response(200, json={"id": "user1"})
    if path == "/auth/users" and method == "GET":
        return httpx.Response(200, json={"users": [{"id": "user1"}]})
    if path == "/auth/admin/reset-password":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/auth/users/user1/role" and method == "PUT":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/auth/admin/unlock/user1":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/auth/users/user1" and method == "DELETE":
        return httpx.Response(200, json={"status": "deleted"})

    # Webhooks
    if path == "/webhooks" and method == "GET":
        return httpx.Response(200, json={"webhooks": [{"id": "wh1"}]})
    if path == "/webhooks" and method == "POST":
        return httpx.Response(200, json={"id": "wh1"})
    if path == "/webhooks/wh1" and method == "DELETE":
        return httpx.Response(200, json={"status": "deleted"})
    if path == "/webhooks/wh1" and method == "PUT":
        return httpx.Response(200, json={"id": "wh1", "updated": True})
    if path == "/webhooks/wh1/test":
        return httpx.Response(200, json={"result": "ok"})
    if path == "/webhooks/stats":
        return httpx.Response(200, json={"total": 0})

    # Forward
    if path == "/forward/targets" and method == "GET":
        return httpx.Response(200, json={"targets": [{"name": "t1"}]})
    if path == "/forward/targets" and method == "POST":
        return httpx.Response(200, json={"name": "t1"})
    if path == "/forward/targets/t1" and method == "DELETE":
        return httpx.Response(200, json={"status": "deleted"})
    if path == "/forward/start":
        return httpx.Response(200, json={"status": "started"})
    if path == "/forward/stop":
        return httpx.Response(200, json={"status": "stopped"})
    if path == "/forward/stats":
        return httpx.Response(200, json={"total": 0})

    # Setup
    if path == "/setup/demo":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/setup/status":
        return httpx.Response(200, json={"initialized": True})

    # Integration / Edgelite
    if path == "/edgelite" and method == "POST":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/edgelite/pygbsentry":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/edgelite/push/dev1" and method == "POST":
        return httpx.Response(200, json={"status": "pushed"})
    if path == "/edgelite/push/dev1" and method == "DELETE":
        return httpx.Response(200, json={"status": "deleted"})
    if path == "/edgelite/test":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/integration/batch-push":
        return httpx.Response(200, json={"pushed": 2})
    if path == "/integration/device/dev1/start":
        return httpx.Response(200, json={"status": "started"})
    if path == "/integration/device/dev1/stop":
        return httpx.Response(200, json={"status": "stopped"})
    if path == "/integration/protocols":
        return httpx.Response(200, json={"protocols": {}})
    if path == "/integration/validate":
        return httpx.Response(200, json={"valid": True})
    if path == "/integration/backhaul-data":
        return httpx.Response(200, json={"data": []})
    if path == "/integration/device-status":
        return httpx.Response(200, json={"devices": {}})
    if path == "/integration/alarm-rules" and method == "GET":
        return httpx.Response(200, json={"rules": [{"id": "r1"}]})
    if path == "/integration/alarm-rules" and method == "POST":
        return httpx.Response(200, json={"id": "r1"})
    if path == "/integration/alarm-rules/r1" and method == "DELETE":
        return httpx.Response(200, json={"status": "deleted"})
    if path == "/integration/status":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/integration/metrics":
        return httpx.Response(200, json={"metrics": {}})

    # Audit
    if path == "/audit" and method == "GET":
        return httpx.Response(200, json={"entries": [], "total": 0})
    if path == "/audit/stats":
        return httpx.Response(200, json={"total": 0})

    # Default
    return httpx.Response(404, json={"detail": "Not Found"})


def _make_sync_client(**kwargs):
    """Create a sync client with mocked transport."""
    transport = httpx.MockTransport(_mock_handler)
    client = ProtoForgeClient(base_url="http://test", **kwargs)
    client._client = httpx.Client(transport=transport)
    return client


def _make_async_client(**kwargs):
    """Create an async client with mocked transport."""
    transport = httpx.MockTransport(_mock_handler)
    client = AsyncProtoForgeClient(base_url="http://test", **kwargs)
    client._client = httpx.AsyncClient(transport=transport)
    return client


# ---------------------------------------------------------------------------
# Sync client tests
# ---------------------------------------------------------------------------

class TestProtoForgeClient:
    def test_init_default_url(self):
        client = ProtoForgeClient()
        assert client._base_url == "http://localhost:8000"
        client.close()

    def test_init_custom_url(self):
        client = ProtoForgeClient(base_url="http://example.com/")
        assert client._base_url == "http://example.com"
        assert client._api_url == "http://example.com/api/v1"
        client.close()

    def test_context_manager(self):
        with ProtoForgeClient(base_url="http://test") as client:
            assert client._base_url == "http://test"

    def test_health(self):
        with _make_sync_client() as c:
            result = c.health()
            assert result["status"] == "ok"

    def test_list_protocols(self):
        with _make_sync_client() as c:
            result = c.list_protocols()
            assert "modbus_tcp" in result

    def test_start_stop_protocol(self):
        with _make_sync_client() as c:
            assert c.start_protocol("modbus_tcp")["status"] == "started"
            assert c.stop_protocol("modbus_tcp")["status"] == "stopped"

    def test_list_devices(self):
        with _make_sync_client() as c:
            result = c.list_devices()
            assert len(result) == 1
            result = c.list_devices(protocol="modbus_tcp")
            assert len(result) == 1

    def test_create_device(self):
        with _make_sync_client() as c:
            r = c.create_device("dev1", "Test", "modbus_tcp")
            assert r["id"] == "dev1"
            r = c.create_device("dev1", "Test", "modbus_tcp", template_id="tpl1", protocol_config={"port": 502})
            assert r["id"] == "dev1"

    def test_quick_create(self):
        with _make_sync_client() as c:
            r = c.quick_create("tpl1", "Test")
            assert r["id"] == "dev1"
            r = c.quick_create("tpl1", "Test", "custom", {"port": 502})
            assert r["id"] == "dev1"

    def test_device_ops(self):
        with _make_sync_client() as c:
            assert c.start_device("dev1")["status"] == "started"
            assert c.stop_device("dev1")["status"] == "stopped"
            assert c.get_device("dev1")["id"] == "dev1"
            assert c.delete_device("dev1")["status"] == "deleted"

    def test_read_write_points(self):
        with _make_sync_client() as c:
            pts = c.read_points("dev1")
            assert len(pts) == 1
            r = c.write_point("dev1", "temp", 42.5)
            assert r["ok"] is True

    def test_batch_ops(self):
        with _make_sync_client() as c:
            assert c.batch_create_devices([{"id": "d1"}])["created"] == 2
            assert c.batch_delete_devices(["d1"])["deleted"] == 2
            assert c.batch_start_devices(["d1"])["started"] == 2
            assert c.batch_stop_devices(["d1"])["stopped"] == 2

    def test_templates(self):
        with _make_sync_client() as c:
            assert len(c.list_templates()) == 1
            assert c.get_template("tpl1")["id"] == "tpl1"
            assert c.create_template({"id": "tpl1"})["id"] == "tpl1"
            assert len(c.search_templates(q="test")) == 1
            assert len(c.search_templates(protocol="modbus")) == 1
            assert len(c.search_templates(tag="tag1")) == 1
            assert len(c.list_template_tags()) == 2
            assert c.instantiate_template("tpl1", "dev1", "Test")["id"] == "dev1"
            assert c.instantiate_template("tpl1", "dev1", "Test", {"port": 502})["id"] == "dev1"

    def test_scenarios(self):
        with _make_sync_client() as c:
            assert len(c.list_scenarios()) == 1
            assert c.create_scenario("sc1", "Test")["id"] == "sc1"
            assert c.get_scenario("sc1")["id"] == "sc1"
            assert c.update_scenario("sc1", {"name": "Updated"})["updated"] is True
            assert c.start_scenario("sc1")["status"] == "started"
            assert c.stop_scenario("sc1")["status"] == "stopped"
            assert c.export_scenario("sc1")["export"] is True
            assert c.import_scenario({"id": "sc1"})["id"] == "sc1"
            assert c.get_scenario_snapshot("sc1")["snapshot"] == {}
            assert c.delete_scenario("sc1")["status"] == "deleted"

    def test_logs(self):
        with _make_sync_client() as c:
            logs = c.get_logs()
            assert len(logs) == 1
            logs = c.get_logs(count=50, protocol="modbus_tcp", device_id="dev1")
            assert len(logs) == 1
            assert c.clear_logs()["status"] == "cleared"

    def test_test_cases(self):
        with _make_sync_client() as c:
            assert c.create_test_case({"id": "case1"})["id"] == "case1"
            assert len(c.list_test_cases()) == 1
            assert len(c.list_test_cases(tag="smoke")) == 1
            assert c.get_test_case("case1")["id"] == "case1"
            assert c.update_test_case("case1", {"name": "Updated"})["updated"] is True
            assert c.delete_test_case("case1")["status"] == "deleted"

    def test_test_suites(self):
        with _make_sync_client() as c:
            assert c.create_test_suite({"id": "suite1"})["id"] == "suite1"
            assert len(c.list_test_suites()) == 1
            assert c.get_test_suite("suite1")["id"] == "suite1"
            assert c.delete_test_suite("suite1")["status"] == "deleted"

    def test_run_tests(self):
        with _make_sync_client() as c:
            assert c.run_tests([{"id": "case1"}])["results"] == []
            assert c.run_test_case("case1")["result"] == "pass"
            assert c.run_test_suite("suite1")["results"] == []

    def test_test_reports(self):
        with _make_sync_client() as c:
            assert len(c.list_test_reports()) == 1
            assert c.get_test_report("rep1")["id"] == "rep1"
            assert "html" in c.get_test_report_html("rep1")
            assert c.get_report_trend() == []
            assert c.get_report_trend(count=5) == []

    def test_quick_test(self):
        with _make_sync_client() as c:
            r = c.quick_test()
            assert r["result"] == "ok"
            r = c.quick_test(scope="device", target_id="dev1")
            assert r["result"] == "ok"

    def test_test_metadata(self):
        with _make_sync_client() as c:
            assert c.get_test_suggestions() == []
            assert c.get_test_action_types() == []
            assert c.get_test_assertion_types() == []

    def test_recorder(self):
        with _make_sync_client() as c:
            assert c.start_recording()["id"] == "rec1"
            assert c.start_recording(protocol="modbus_tcp", device_id="dev1")["id"] == "rec1"
            assert c.stop_recording()["status"] == "stopped"
            assert len(c.list_recordings()) == 1
            assert c.get_recording("rec1")["id"] == "rec1"
            assert c.export_recording("rec1")["id"] == "rec1"
            assert c.delete_recording("rec1")["status"] == "deleted"
            stats = c.get_recorder_stats()
            assert "is_recording" in stats

    def test_settings(self):
        with _make_sync_client() as c:
            assert c.get_settings()["key"] == "value"
            assert c.update_settings({"key": "new"})["updated"] is True

    def test_auth(self):
        with _make_sync_client() as c:
            r = c.login("admin", "pass")
            assert r["access_token"] == "tok123"
            assert c._client.headers["Authorization"] == "Bearer tok123"
            assert c.refresh_token("tok123")["access_token"] == "tok456"
            assert c.change_password("admin", "old", "new")["status"] == "ok"
            assert c.register("user1", "pass")["id"] == "user1"
            assert len(c.list_users()) == 1
            assert c.admin_reset_password("user1", "newpass")["status"] == "ok"
            assert c.update_user_role("user1", "admin")["status"] == "ok"
            assert c.admin_unlock_user("user1")["status"] == "ok"
            assert c.delete_user("user1")["status"] == "deleted"

    def test_webhooks(self):
        with _make_sync_client() as c:
            assert len(c.list_webhooks()) == 1
            assert c.add_webhook({"url": "http://example.com"})["id"] == "wh1"
            assert c.update_webhook("wh1", {"url": "http://new.com"})["updated"] is True
            assert c.test_webhook("wh1")["result"] == "ok"
            assert c.get_webhook_stats()["total"] == 0
            assert c.delete_webhook("wh1")["status"] == "deleted"

    def test_forward(self):
        with _make_sync_client() as c:
            assert len(c.list_forward_targets()) == 1
            assert c.add_forward_target({"name": "t1"})["name"] == "t1"
            assert c.start_forward()["status"] == "started"
            assert c.stop_forward()["status"] == "stopped"
            assert c.get_forward_stats()["total"] == 0
            assert c.remove_forward_target("t1")["status"] == "deleted"

    def test_setup(self):
        with _make_sync_client() as c:
            assert c.setup_demo()["status"] == "ok"
            assert c.get_setup_status()["initialized"] is True

    def test_integration(self):
        with _make_sync_client() as c:
            assert c.import_edgelite({"config": 1})["status"] == "ok"
            assert c.import_pygbsentry({"config": 1})["status"] == "ok"
            assert c.push_device_integration("dev1")["status"] == "pushed"
            assert c.batch_push(["dev1"])["pushed"] == 2
            assert c.delete_device_from_edgelite("dev1")["status"] == "deleted"
            assert c.start_device_collect("dev1")["status"] == "started"
            assert c.stop_device_collect("dev1")["status"] == "stopped"
            assert "protocols" in c.get_protocol_mappings()
            assert c.validate_device_compatibility("dev1")["valid"] is True
            assert c.validate_device_compatibility("dev1", protocol="modbus", points=[{"name": "x"}], driver_config={"k": "v"})["valid"] is True
            assert c.test_integration_connection({"url": "http://test"})["status"] == "ok"
            assert "data" in c.get_backhaul_data()
            assert "data" in c.get_backhaul_data(device_id="dev1", limit=50)
            assert "devices" in c.get_device_status_cache()
            assert len(c.get_alarm_rules()) == 1
            assert c.add_alarm_rule({"id": "r1"})["id"] == "r1"
            assert c.delete_alarm_rule("r1")["status"] == "deleted"
            assert c.get_integration_status()["status"] == "ok"
            assert "metrics" in c.get_integration_metrics()

    def test_audit(self):
        with _make_sync_client() as c:
            r = c.query_audit_log()
            assert "entries" in r
            r = c.query_audit_log(user="admin", action="login")
            assert "entries" in r
            assert c.get_audit_stats()["total"] == 0

    def test_protocols_info(self):
        with _make_sync_client() as c:
            assert len(c.get_protocols_info()) == 1
            assert c.get_protocol_config("modbus_tcp")["port"] == 502
            assert c.get_protocol_device_config("modbus_tcp")["template"] == "default"

    def test_update_device(self):
        with _make_sync_client() as c:
            r = c.update_device("dev1", {"name": "Updated"})
            assert r["updated"] is True

    def test_get_device_config_and_guide(self):
        with _make_sync_client() as c:
            assert c.get_device_config("dev1")["protocol"] == "modbus_tcp"
            assert c.get_device_connection_guide("dev1")["guide"] == "connect here"

    def test_retry_on_connect_error(self):
        call_count = {"n": 0}

        def handler(request):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise httpx.ConnectError("connection refused")
            return httpx.Response(200, json={"status": "ok"})

        client = ProtoForgeClient(base_url="http://test", retries=2, retry_delay=0.01)
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        result = client.health()
        assert result["status"] == "ok"
        assert call_count["n"] == 2
        client.close()

    def test_retry_exhausted(self):
        def handler(request):
            raise httpx.ConnectError("connection refused")

        client = ProtoForgeClient(base_url="http://test", retries=1, retry_delay=0.01)
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(httpx.ConnectError):
            client.health()
        client.close()

    def test_http_error_raises(self):
        def handler(request):
            return httpx.Response(500, json={"detail": "Internal Error"})

        client = ProtoForgeClient(base_url="http://test")
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(httpx.HTTPStatusError):
            client.health()
        client.close()

    def test_unwrap_list_variants(self):
        # Test direct list response
        def list_handler(request):
            return httpx.Response(200, json=["a", "b", "c"])

        client = ProtoForgeClient(base_url="http://test")
        client._client = httpx.Client(transport=httpx.MockTransport(list_handler))
        result = client._unwrap_list("/test")
        assert result == ["a", "b", "c"]
        client.close()

        # Test dict with list value (no key)
        def dict_handler(request):
            return httpx.Response(200, json={"items": ["x", "y"]})

        client2 = ProtoForgeClient(base_url="http://test")
        client2._client = httpx.Client(transport=httpx.MockTransport(dict_handler))
        result = client2._unwrap_list("/test")
        assert result == ["x", "y"]
        client2.close()

        # Test dict with no list value
        def empty_handler(request):
            return httpx.Response(200, json={"count": 0})

        client3 = ProtoForgeClient(base_url="http://test")
        client3._client = httpx.Client(transport=httpx.MockTransport(empty_handler))
        result = client3._unwrap_list("/test")
        assert result == []
        client3.close()


# ---------------------------------------------------------------------------
# Async client tests
# ---------------------------------------------------------------------------

class TestAsyncProtoForgeClient:
    @pytest.mark.asyncio
    async def test_init_default_url(self):
        client = AsyncProtoForgeClient()
        assert client._base_url == "http://localhost:8000"
        await client.close()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with AsyncProtoForgeClient(base_url="http://test") as client:
            assert client._base_url == "http://test"

    @pytest.mark.asyncio
    async def test_health(self):
        async with _make_async_client() as c:
            result = await c.health()
            assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_list_protocols(self):
        async with _make_async_client() as c:
            result = await c.list_protocols()
            assert "modbus_tcp" in result

    @pytest.mark.asyncio
    async def test_list_devices(self):
        async with _make_async_client() as c:
            result = await c.list_devices()
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_create_device(self):
        async with _make_async_client() as c:
            r = await c.create_device("dev1", "Test", "modbus_tcp")
            assert r["id"] == "dev1"

    @pytest.mark.asyncio
    async def test_device_ops(self):
        async with _make_async_client() as c:
            assert (await c.start_device("dev1"))["status"] == "started"
            assert (await c.stop_device("dev1"))["status"] == "stopped"
            assert (await c.get_device("dev1"))["id"] == "dev1"
            assert (await c.delete_device("dev1"))["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_read_write_points(self):
        async with _make_async_client() as c:
            pts = await c.read_points("dev1")
            assert len(pts) == 1
            r = await c.write_point("dev1", "temp", 42.5)
            assert r["ok"] is True

    @pytest.mark.asyncio
    async def test_templates(self):
        async with _make_async_client() as c:
            assert len(await c.list_templates()) == 1
            assert (await c.get_template("tpl1"))["id"] == "tpl1"

    @pytest.mark.asyncio
    async def test_scenarios(self):
        async with _make_async_client() as c:
            assert len(await c.list_scenarios()) == 1
            assert (await c.create_scenario("sc1", "Test"))["id"] == "sc1"
            assert (await c.start_scenario("sc1"))["status"] == "started"

    @pytest.mark.asyncio
    async def test_recorder(self):
        async with _make_async_client() as c:
            assert (await c.start_recording())["id"] == "rec1"
            assert (await c.stop_recording())["status"] == "stopped"
            stats = await c.get_recorder_stats()
            assert "is_recording" in stats

    @pytest.mark.asyncio
    async def test_auth(self):
        async with _make_async_client() as c:
            r = await c.login("admin", "pass")
            assert r["access_token"] == "tok123"

    @pytest.mark.asyncio
    async def test_settings(self):
        async with _make_async_client() as c:
            assert (await c.get_settings())["key"] == "value"

    @pytest.mark.asyncio
    async def test_retry_on_connect_error(self):
        call_count = {"n": 0}

        def handler(request):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise httpx.ConnectError("connection refused")
            return httpx.Response(200, json={"status": "ok"})

        client = AsyncProtoForgeClient(base_url="http://test", retries=2, retry_delay=0.01)
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        result = await client.health()
        assert result["status"] == "ok"
        assert call_count["n"] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_http_error_raises(self):
        def handler(request):
            return httpx.Response(500, json={"detail": "Internal Error"})

        client = AsyncProtoForgeClient(base_url="http://test")
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(httpx.HTTPStatusError):
            await client.health()
        await client.close()
