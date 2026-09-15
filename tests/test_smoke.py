"""Smoke tests for ProtoForge application startup and core endpoints.

These tests verify that the application can start successfully and that
key API endpoints respond correctly. They serve as E2E availability checks.

Run only smoke tests with:
    pytest -m smoke -v
"""

import pytest
from httpx import AsyncClient

# Module-level marker: ensures every test in this file is tagged as smoke.
# Also applied per-function below for explicitness and `pytest -m smoke` filtering.
pytestmark = pytest.mark.smoke


@pytest.mark.asyncio
async def test_smoke_health_endpoint(client: AsyncClient):
    """Health endpoint should return 200 with status=ok."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_smoke_api_v1_health(client: AsyncClient):
    """API v1 health endpoint should return 200."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_smoke_root_page(client: AsyncClient):
    """Root endpoint should serve HTML."""
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_smoke_list_protocols(client: AsyncClient):
    """Protocol listing endpoint should return available protocols."""
    response = await client.get("/api/v1/protocols")
    assert response.status_code == 200
    data = response.json()
    assert "protocols" in data
    assert len(data["protocols"]) >= 2


@pytest.mark.asyncio
async def test_smoke_list_templates(client: AsyncClient):
    """Template listing endpoint should return templates."""
    response = await client.get("/api/v1/templates")
    assert response.status_code == 200
    data = response.json()
    assert "templates" in data
    assert len(data["templates"]) >= 1


@pytest.mark.asyncio
async def test_smoke_create_and_delete_device(client: AsyncClient):
    """Device CRUD: create, read, delete should work end-to-end."""
    device_config = {
        "id": "smoke-test-device",
        "name": "smoke-test",
        "protocol": "modbus_tcp",
        "points": [
            {
                "name": "temperature",
                "address": "0",
                "data_type": "float32",
                "unit": "C",
                "generator_type": "random",
                "min_value": 15.0,
                "max_value": 35.0,
            }
        ],
    }
    # Create
    response = await client.post("/api/v1/devices", json=device_config)
    assert response.status_code == 200

    # Read
    response = await client.get("/api/v1/devices/smoke-test-device")
    assert response.status_code == 200
    assert response.json()["id"] == "smoke-test-device"

    # Read points
    response = await client.get("/api/v1/devices/smoke-test-device/points")
    assert response.status_code == 200

    # Delete
    response = await client.delete("/api/v1/devices/smoke-test-device")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_smoke_list_devices(client: AsyncClient):
    """Device listing endpoint should return a list."""
    response = await client.get("/api/v1/devices")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_smoke_logs_endpoint(client: AsyncClient):
    """Logs endpoint should return log entries."""
    response = await client.get("/api/v1/logs")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "entries" in data


@pytest.mark.asyncio
async def test_smoke_scenario_crud(client: AsyncClient):
    """Scenario CRUD: create, read, export should work."""
    scenario_config = {
        "id": "smoke-test-scenario",
        "name": "smoke-scenario",
        "description": "smoke test",
        "devices": [],
        "rules": [],
    }
    # Create
    response = await client.post("/api/v1/scenarios", json=scenario_config)
    assert response.status_code == 200

    # Read
    response = await client.get("/api/v1/scenarios/smoke-test-scenario")
    assert response.status_code == 200

    # Export
    response = await client.get("/api/v1/scenarios/smoke-test-scenario/export")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_smoke_protocol_info(client: AsyncClient):
    """Protocol info endpoint should return protocol configurations."""
    response = await client.get("/api/v1/protocols/info")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_smoke_metrics_endpoint(client: AsyncClient):
    """Metrics endpoint should be accessible."""
    response = await client.get("/metrics")
    # Metrics may require auth or return 200
    assert response.status_code in (200, 401, 403)


@pytest.mark.asyncio
async def test_smoke_auth_me_endpoint(client: AsyncClient):
    """Auth subsystem should respond: /auth/me returns current user (admin in no-auth mode)."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200
    data = response.json()
    # In no-auth test mode the middleware injects an admin user
    assert "username" in data


@pytest.mark.asyncio
async def test_smoke_auth_login_reachable(client: AsyncClient):
    """Auth login endpoint should be reachable and reject empty body gracefully."""
    response = await client.post("/api/v1/auth/login", json={"username": "smoke", "password": "no-such-user"})
    # Invalid credentials -> 401; endpoint reachability is the smoke concern
    assert response.status_code in (401, 423)


@pytest.mark.asyncio
async def test_smoke_system_setup_status(client: AsyncClient):
    """System setup/status endpoint should return system readiness information."""
    response = await client.get("/api/v1/setup/status")
    assert response.status_code == 200
    data = response.json()
    assert "initialized" in data
    assert "device_count" in data
