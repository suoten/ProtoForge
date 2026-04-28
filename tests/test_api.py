import os

import pytest
import pytest_asyncio

os.environ["PROTOFORGE_NO_AUTH"] = "1"

from httpx import ASGITransport, AsyncClient

from protoforge.core.engine import SimulationEngine
from protoforge.core.log_bus import LogBus
from protoforge.core.template import TemplateManager
from protoforge.protocols.http.server import HttpSimulatorServer
from protoforge.protocols.modbus.server import ModbusTcpServer
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


@pytest.mark.asyncio
async def test_root(client: AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_list_protocols(client: AsyncClient):
    response = await client.get("/api/v1/protocols")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    names = [p["name"] for p in data]
    assert "modbus_tcp" in names
    assert "http" in names


@pytest.mark.asyncio
async def test_list_templates(client: AsyncClient):
    response = await client.get("/api/v1/templates")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 6


@pytest.mark.asyncio
async def test_create_and_get_device(client: AsyncClient):
    device_config = {
        "id": "test-device-001",
        "name": "test-sensor",
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
    response = await client.post("/api/v1/devices", json=device_config)
    assert response.status_code == 200

    response = await client.get("/api/v1/devices/test-device-001")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test-device-001"
    assert data["name"] == "test-sensor"

    response = await client.get("/api/v1/devices/test-device-001/points")
    assert response.status_code == 200
    assert len(response.json()) >= 1

    response = await client.delete("/api/v1/devices/test-device-001")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_scenario_crud(client: AsyncClient):
    scenario_config = {
        "id": "test-scenario-001",
        "name": "test-scenario",
        "description": "test",
        "devices": [],
        "rules": [],
    }
    response = await client.post("/api/v1/scenarios", json=scenario_config)
    assert response.status_code == 200

    response = await client.get("/api/v1/scenarios/test-scenario-001")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test-scenario-001"


@pytest.mark.asyncio
async def test_scenario_export(client: AsyncClient):
    scenario_config = {
        "id": "test-export-001",
        "name": "export-test",
        "description": "test export",
        "devices": [],
        "rules": [],
    }
    await client.post("/api/v1/scenarios", json=scenario_config)
    response = await client.get("/api/v1/scenarios/test-export-001/export")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test-export-001"
    assert data["name"] == "export-test"


@pytest.mark.asyncio
async def test_logs_endpoint(client: AsyncClient):
    response = await client.get("/api/v1/logs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_http_protocol_device(client: AsyncClient):
    device_config = {
        "id": "http-device-001",
        "name": "http-test",
        "protocol": "http",
        "points": [
            {
                "name": "status",
                "address": "/status",
                "data_type": "string",
                "generator_type": "fixed",
                "fixed_value": "running",
            }
        ],
    }
    response = await client.post("/api/v1/devices", json=device_config)
    assert response.status_code == 200

    response = await client.get("/api/v1/devices/http-device-001/points")
    assert response.status_code == 200
    points = response.json()
    assert len(points) == 1
    assert points[0]["value"] == "running"

    await client.delete("/api/v1/devices/http-device-001")
