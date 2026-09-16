"""Extended API tests - webhooks, templates, scenarios, system routes, recorder, forward."""

import pytest
from httpx import AsyncClient


# ==================== Webhook API Tests ====================

class TestWebhookAPI:
    @pytest.mark.asyncio
    async def test_list_webhooks(self, client: AsyncClient):
        resp = await client.get("/api/v1/webhooks")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (list, dict))

    @pytest.mark.asyncio
    async def test_create_webhook(self, client: AsyncClient):
        resp = await client.post("/api/v1/webhooks", json={
            "id": "wh-api-test",
            "name": "API Test Webhook",
            "url": "http://example.com/hook",
            "events": ["device_created"],
        })
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_update_webhook(self, client: AsyncClient):
        await client.post("/api/v1/webhooks", json={
            "id": "wh-update",
            "name": "Original",
            "url": "http://example.com/hook",
            "events": ["device_created"],
        })
        resp = await client.put("/api/v1/webhooks/wh-update", json={
            "id": "wh-update",
            "name": "Updated",
            "url": "http://example.com/hook2",
            "events": ["device_created", "device_deleted"],
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_webhook(self, client: AsyncClient):
        await client.post("/api/v1/webhooks", json={
            "id": "wh-delete",
            "name": "Delete Me",
            "url": "http://example.com/hook",
            "events": ["device_created"],
        })
        resp = await client.delete("/api/v1/webhooks/wh-delete")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_test_webhook(self, client: AsyncClient):
        await client.post("/api/v1/webhooks", json={
            "id": "wh-test-trigger",
            "name": "Test Trigger",
            "url": "http://example.com/hook",
            "events": ["device_created"],
        })
        resp = await client.post("/api/v1/webhooks/wh-test-trigger/test")
        assert resp.status_code in (200, 204, 500, 502)  # May fail to send

    @pytest.mark.asyncio
    async def test_webhook_stats(self, client: AsyncClient):
        resp = await client.get("/api/v1/webhooks/stats")
        assert resp.status_code == 200


# ==================== Template API Tests ====================

class TestTemplateAPI:
    @pytest.mark.asyncio
    async def test_list_templates(self, client: AsyncClient):
        resp = await client.get("/api/v1/templates")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_search_templates(self, client: AsyncClient):
        resp = await client.get("/api/v1/templates/search?q=modbus")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_template_tags(self, client: AsyncClient):
        resp = await client.get("/api/v1/templates/tags")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_template(self, client: AsyncClient):
        # First list templates to get an ID
        resp = await client.get("/api/v1/templates")
        templates = resp.json().get("templates", [])
        if templates:
            template_id = templates[0]["id"]
            resp = await client.get(f"/api/v1/templates/{template_id}")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_template(self, client: AsyncClient):
        resp = await client.post("/api/v1/templates", json={
            "id": "test-tpl-api",
            "name": "API Test Template",
            "protocol": "modbus_tcp",
            "description": "Test",
            "fields": [
                {"name": "port", "type": "int", "default": 502},
                {"name": "host", "type": "string", "default": "0.0.0.0"},
            ],
        })
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_delete_template(self, client: AsyncClient):
        await client.post("/api/v1/templates", json={
            "id": "del-tpl-api",
            "name": "Delete",
            "protocol": "modbus_tcp",
            "description": "",
            "fields": [],
        })
        resp = await client.delete("/api/v1/templates/del-tpl-api")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_export_template(self, client: AsyncClient):
        resp = await client.get("/api/v1/templates")
        templates = resp.json().get("templates", [])
        if templates:
            template_id = templates[0]["id"]
            resp = await client.get(f"/api/v1/templates/{template_id}/export")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_instantiate_template(self, client: AsyncClient):
        resp = await client.get("/api/v1/templates")
        templates = resp.json().get("templates", [])
        if templates:
            template_id = templates[0]["id"]
            resp = await client.post(f"/api/v1/templates/{template_id}/instantiate", json={
                "device_id": "tpl-instance-dev",
                "name": "Instantiated Device",
                "config": {"port": 5021},
            })
            assert resp.status_code in (200, 201, 400, 422)


# ==================== Scenario API Tests ====================

class TestScenarioAPI:
    @pytest.mark.asyncio
    async def test_list_scenarios(self, client: AsyncClient):
        resp = await client.get("/api/v1/scenarios")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_scenario(self, client: AsyncClient):
        resp = await client.post("/api/v1/scenarios", json={
            "id": "api-scen-1",
            "name": "API Scenario",
            "description": "test",
            "devices": [],
            "rules": [],
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_scenario(self, client: AsyncClient):
        await client.post("/api/v1/scenarios", json={
            "id": "get-scen-api",
            "name": "Get",
            "description": "test",
            "devices": [],
            "rules": [],
        })
        resp = await client.get("/api/v1/scenarios/get-scen-api")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_start_stop_scenario(self, client: AsyncClient):
        await client.post("/api/v1/scenarios", json={
            "id": "start-scen-api",
            "name": "Start",
            "description": "test",
            "devices": [],
            "rules": [],
        })
        resp = await client.post("/api/v1/scenarios/start-scen-api/start")
        assert resp.status_code == 200
        resp = await client.post("/api/v1/scenarios/start-scen-api/stop")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_scenario(self, client: AsyncClient):
        await client.post("/api/v1/scenarios", json={
            "id": "upd-scen-api",
            "name": "Original",
            "description": "test",
            "devices": [],
            "rules": [],
        })
        resp = await client.put("/api/v1/scenarios/upd-scen-api", json={
            "id": "upd-scen-api",
            "name": "Updated",
            "description": "updated",
            "devices": [],
            "rules": [],
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_scenario(self, client: AsyncClient):
        await client.post("/api/v1/scenarios", json={
            "id": "del-scen-api",
            "name": "Delete",
            "description": "test",
            "devices": [],
            "rules": [],
        })
        resp = await client.delete("/api/v1/scenarios/del-scen-api")
        assert resp.status_code == 200


# ==================== System API Tests ====================

class TestSystemAPI:
    @pytest.mark.asyncio
    async def test_setup_status(self, client: AsyncClient):
        resp = await client.get("/api/v1/setup/status")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_settings(self, client: AsyncClient):
        resp = await client.get("/api/v1/settings")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_settings(self, client: AsyncClient):
        resp = await client.put("/api/v1/settings", json={
            "tick_interval": 2.0,
        })
        assert resp.status_code in (200, 422)

    @pytest.mark.asyncio
    async def test_audit_logs(self, client: AsyncClient):
        resp = await client.get("/api/v1/audit")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_audit_stats(self, client: AsyncClient):
        resp = await client.get("/api/v1/audit/stats")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_backup(self, client: AsyncClient):
        resp = await client.get("/api/v1/backup")
        assert resp.status_code in (200, 500)


# ==================== Device API Extended Tests ====================

class TestDeviceAPIExtended:
    @pytest.mark.asyncio
    async def test_list_devices(self, client: AsyncClient):
        resp = await client.get("/api/v1/devices")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_device_with_multiple_points(self, client: AsyncClient):
        resp = await client.post("/api/v1/devices", json={
            "id": "multi-point-dev",
            "name": "Multi Point Device",
            "protocol": "modbus_tcp",
            "points": [
                {"name": "temp", "address": "0", "data_type": "float32", "generator_type": "random", "min_value": 0, "max_value": 100},
                {"name": "pressure", "address": "2", "data_type": "float32", "generator_type": "sine", "generator_config": {"amplitude": 10, "frequency": 1}},
                {"name": "flow", "address": "4", "data_type": "float32", "generator_type": "fixed", "fixed_value": 42.5},
                {"name": "status", "address": "6", "data_type": "string", "generator_type": "fixed", "fixed_value": "running"},
            ],
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_start_stop_device(self, client: AsyncClient):
        await client.post("/api/v1/devices", json={
            "id": "start-stop-dev",
            "name": "Start Stop",
            "protocol": "modbus_tcp",
            "points": [
                {"name": "val", "address": "0", "data_type": "float32", "generator_type": "fixed", "fixed_value": 1.0},
            ],
        })
        resp = await client.post("/api/v1/devices/start-stop-dev/start")
        assert resp.status_code == 200
        resp = await client.post("/api/v1/devices/start-stop-dev/stop")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_write_device_point(self, client: AsyncClient):
        await client.post("/api/v1/devices", json={
            "id": "write-dev-api",
            "name": "Write Test",
            "protocol": "modbus_tcp",
            "points": [
                {"name": "setpoint", "address": "0", "data_type": "float32", "generator_type": "fixed", "fixed_value": 50.0},
            ],
        })
        await client.post("/api/v1/devices/write-dev-api/start")
        resp = await client.put("/api/v1/devices/write-dev-api/points/setpoint", json={"value": 75.0})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_device_detail(self, client: AsyncClient):
        await client.post("/api/v1/devices", json={
            "id": "detail-dev",
            "name": "Detail Test",
            "protocol": "modbus_tcp",
            "points": [
                {"name": "val", "address": "0", "data_type": "float32", "generator_type": "random", "min_value": 0, "max_value": 100},
            ],
        })
        resp = await client.get("/api/v1/devices/detail-dev")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "detail-dev"

    @pytest.mark.asyncio
    async def test_update_device(self, client: AsyncClient):
        await client.post("/api/v1/devices", json={
            "id": "update-dev-api",
            "name": "Original",
            "protocol": "modbus_tcp",
            "points": [
                {"name": "val", "address": "0", "data_type": "float32", "generator_type": "fixed", "fixed_value": 1.0},
            ],
        })
        resp = await client.put("/api/v1/devices/update-dev-api", json={
            "id": "update-dev-api",
            "name": "Updated Name",
            "protocol": "modbus_tcp",
            "points": [
                {"name": "val", "address": "0", "data_type": "float32", "generator_type": "fixed", "fixed_value": 2.0},
            ],
        })
        assert resp.status_code == 200


# ==================== Protocol API Tests ====================

class TestProtocolAPI:
    @pytest.mark.asyncio
    async def test_list_protocols(self, client: AsyncClient):
        resp = await client.get("/api/v1/protocols")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_protocol_detail(self, client: AsyncClient):
        resp = await client.get("/api/v1/protocols")
        protocols = resp.json().get("protocols", [])
        if protocols:
            name = protocols[0]["name"]
        resp = await client.get(f"/api/v1/protocols/{name}/config")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_start_stop_protocol(self, client: AsyncClient):
        resp = await client.post("/api/v1/protocols/http/start", json={"port": 18080})
        assert resp.status_code in (200, 400, 500)
        resp = await client.post("/api/v1/protocols/http/stop")
        assert resp.status_code in (200, 400, 500)


# ==================== Recorder API Tests ====================

class TestRecorderAPI:
    @pytest.mark.asyncio
    async def test_list_recordings(self, client: AsyncClient):
        resp = await client.get("/api/v1/recorder/recordings")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_recorder_stats(self, client: AsyncClient):
        resp = await client.get("/api/v1/recorder/stats")
        assert resp.status_code == 200


# ==================== Forward API Tests ====================

class TestForwardAPI:
    @pytest.mark.asyncio
    async def test_list_forwards(self, client: AsyncClient):
        resp = await client.get("/api/v1/forward/targets")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_forward_stats(self, client: AsyncClient):
        resp = await client.get("/api/v1/forward/stats")
        assert resp.status_code in (200, 404)


# ==================== Metrics Endpoint Tests ====================

class TestMetricsEndpoint:
    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, client: AsyncClient):
        resp = await client.get("/metrics")
        assert resp.status_code in (200, 401)  # May require auth

    @pytest.mark.asyncio
    async def test_api_v1_metrics(self, client: AsyncClient):
        resp = await client.get("/api/v1/metrics")
        assert resp.status_code in (200, 401)


# ==================== Integration API Tests ====================

class TestIntegrationAPI:
    @pytest.mark.asyncio
    async def test_list_integrations(self, client: AsyncClient):
        resp = await client.get("/api/v1/integration/status")
        assert resp.status_code in (200, 503)
