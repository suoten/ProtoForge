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


@pytest.mark.asyncio
async def test_batch_create_devices(client):
    configs = [
        {"id": "batch-001", "name": "Batch1", "protocol": "http", "points": []},
        {"id": "batch-002", "name": "Batch2", "protocol": "http", "points": []},
    ]
    response = await client.post("/api/v1/devices/batch", json=configs)
    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 2

    response = await client.request("DELETE", "/api/v1/devices/batch", json=["batch-001", "batch-002"])
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_template_search(client):
    response = await client.get("/api/v1/templates/search", params={"q": "温度"})
    assert response.status_code == 200

    response = await client.get("/api/v1/templates/search", params={"protocol": "modbus_tcp"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 3

    response = await client.get("/api/v1/templates/search", params={"tag": "环境监控"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_template_tags(client):
    response = await client.get("/api/v1/templates/tags")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0


@pytest.mark.asyncio
async def test_scenario_snapshot(client):
    scenario_config = {
        "id": "snap-test-001",
        "name": "Snapshot Test",
        "description": "test",
        "devices": [
            {"id": "snap-dev-001", "name": "SnapDevice", "protocol": "http",
             "points": [{"name": "val", "address": "0", "data_type": "float32",
                         "generator_type": "random", "min_value": 0, "max_value": 100}]},
        ],
        "rules": [],
    }
    await client.post("/api/v1/scenarios", json=scenario_config)
    await client.post("/api/v1/scenarios/snap-test-001/start")

    response = await client.get("/api/v1/scenarios/snap-test-001/snapshot")
    assert response.status_code == 200
    data = response.json()
    assert data["scenario_id"] == "snap-test-001"
    assert "devices" in data
    assert "timestamp" in data

    await client.post("/api/v1/scenarios/snap-test-001/stop")
