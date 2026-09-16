"""E2E EdgeLite joint-debugging verification.

This is the core "EdgeLite 联调真正可用" deliverable. It spins up a lightweight
EdgeLite API mock (a real aiohttp HTTP server on a real port) and drives the
full ProtoForge → EdgeLite integration pipeline:

1. **convert_device_to_edgelite** — device config → EdgeLite payload translation
2. **push_device** — REST push to EdgeLite (auth + compatibility + protocol-running checks)
3. **verify_pipeline** — 4-step end-to-end verification (auth → register → connect → collect)
   with auto_fix (auto-push unregistered devices) and offline detection

The mocked EdgeLite server implements the exact API surface that
``IntegrationManager`` talks to:
    - POST /api/v1/auth/login          → access token
    - GET  /api/v1/auth/me             → user profile (must_change_password=false)
    - GET  /api/v1/drivers/protocols   → supported protocol list
    - POST /api/v1/integration/push-device → register a device
    - GET  /api/v1/devices/{id}        → device status (online/offline/404)
    - GET  /api/v1/devices/{id}/points → collected point values

This is a *real-machine* test: actual TCP sockets, actual HTTP frames, actual
httpx async client inside IntegrationManager — not mocks of the manager itself.
"""

from __future__ import annotations

import asyncio
import os

os.environ["PROTOFORGE_NO_AUTH"] = "1"
os.environ.setdefault("PROTOFORGE_DB_PATH", "sqlite:///./data/test_e2e_edgelite.db")

import pytest
import pytest_asyncio

from protoforge.engine.engine import SimulationEngine
from protoforge.engine.event_bus import EventBus
from protoforge.integrations.integration.manager import IntegrationManager
from protoforge.observability.log_bus import LogBus
from protoforge.engine.registry import (
    clear_all as _clear_registry,
    register_database as _register_database,
    register_engine as _register_engine,
    register_log_bus as _register_log_bus,
)
from protoforge.models.device import DataType, DeviceConfig, GeneratorType, PointConfig
import protoforge.main as main_module


# ---------------------------------------------------------------------------
#  Shared engine/db helpers (mirrors test_e2e_multi_protocol_real.py)
# ---------------------------------------------------------------------------


async def _setup_engine_and_db():
    """Create a fresh engine + database for E2E testing."""
    main_module._log_bus = LogBus()
    from protoforge.db.session import Database

    main_module._database = Database()
    await main_module._database.connect()

    engine = SimulationEngine()
    await engine.start()
    _register_engine(engine)
    _register_database(main_module._database)
    _register_log_bus(main_module._log_bus)
    return engine


async def _teardown_engine_and_db(engine):
    await engine.stop()
    await main_module._database.close()
    main_module._engine = None
    main_module._database = None
    main_module._log_bus = None
    _clear_registry()


# ---------------------------------------------------------------------------
#  Mocked EdgeLite API server (real aiohttp HTTP server)
# ---------------------------------------------------------------------------


class MockEdgeLiteState:
    """Mutable state backing the mocked EdgeLite API."""

    def __init__(self):
        self.devices: dict[str, dict] = {}  # device_id -> {status, points}
        self.login_count = 0
        self.push_count = 0
        self.pushed_payloads: list[dict] = []

    def register_device(self, device_id: str, status: str = "online", points: list[dict] | None = None):
        self.devices[device_id] = {
            "status": status,
            "points": points or [{"name": "temperature", "value": 25.8}],
        }

    def set_status(self, device_id: str, status: str):
        if device_id in self.devices:
            self.devices[device_id]["status"] = status
        else:
            self.register_device(device_id, status=status)


async def _start_mocked_edgelite(state: MockEdgeLiteState):
    """Start a real aiohttp server emulating the EdgeLite REST API.

    Returns (base_url, runner) — caller must ``await runner.cleanup()``.
    """
    from aiohttp import web

    async def login(request):
        state.login_count += 1
        return web.json_response({
            "data": {
                "access_token": "test-token",
                "refresh_token": "test-refresh",
                "csrf_token": "",
                "expires_in": 86400,
            }
        })

    async def auth_me(request):
        return web.json_response({"data": {"username": "admin", "must_change_password": False}})

    async def drivers_protocols(request):
        return web.json_response({
            "data": {"protocols": ["modbus_tcp", "opcua", "mqtt", "http", "s7"]}
        })

    async def push_device(request):
        payload = await request.json()
        state.push_count += 1
        state.pushed_payloads.append(payload)
        dev_id = payload.get("device_id", "unknown")
        pts = payload.get("points", [])
        # Normalize points to {name, value} for the points endpoint
        norm_points = []
        for p in pts:
            if isinstance(p, dict):
                norm_points.append({"name": p.get("name", "x"), "value": 25.8})
        state.register_device(dev_id, status="online", points=norm_points or [{"name": "temperature", "value": 25.8}])
        return web.json_response({"data": {"device_id": dev_id, "status": "online"}}, status=201)

    async def get_device(request):
        dev_id = request.match_info["device_id"]
        dev = state.devices.get(dev_id)
        if not dev:
            return web.json_response({"detail": "not found"}, status=404)
        return web.json_response({"data": {"device_id": dev_id, "status": dev["status"]}})

    async def get_points(request):
        dev_id = request.match_info["device_id"]
        dev = state.devices.get(dev_id, {"points": []})
        return web.json_response({"data": dev.get("points", [])})

    app = web.Application()
    app.router.add_post("/api/v1/auth/login", login)
    app.router.add_get("/api/v1/auth/me", auth_me)
    app.router.add_get("/api/v1/drivers/protocols", drivers_protocols)
    app.router.add_post("/api/v1/integration/push-device", push_device)
    app.router.add_get("/api/v1/devices/{device_id}", get_device)
    app.router.add_get("/api/v1/devices/{device_id}/points", get_points)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)  # 0 = random free port
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return f"http://127.0.0.1:{port}", runner


# ---------------------------------------------------------------------------
#  Test device factory
# ---------------------------------------------------------------------------

MODBUS_TEST_PORT = 15021


def _make_modbus_device(edgelite_url: str, device_id: str = "e2e-edgelite-modbus") -> DeviceConfig:
    return DeviceConfig(
        id=device_id,
        name="E2E EdgeLite Modbus Device",
        protocol="modbus_tcp",
        protocol_config={
            "host": "127.0.0.1",
            "port": MODBUS_TEST_PORT,
            "slave_id": 1,
            "unit_id": 1,
            "edgelite_url": edgelite_url,
            "edgelite_username": "admin",
            "edgelite_password": "admin",
        },
        points=[
            PointConfig(
                name="temperature",
                address="10",
                data_type=DataType.FLOAT32,
                generator_type=GeneratorType.FIXED,
                fixed_value=25.8,
                access="rw",
            ),
        ],
    )


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def joint_env():
    """Start mocked EdgeLite + engine with Modbus running + IntegrationManager.

    Yields (engine, manager, edgelite_url, state, device).
    """
    state = MockEdgeLiteState()
    edgelite_url, runner = await _start_mocked_edgelite(state)

    engine = await _setup_engine_and_db()

    # Register & start the Modbus protocol server (push_device requires running)
    from protoforge.protocols.modbus.server import ModbusTcpServer

    engine.register_protocol(ModbusTcpServer())
    device = _make_modbus_device(edgelite_url)
    await engine.create_device(device)
    await engine.start_protocol("modbus_tcp", {"host": "127.0.0.1", "port": MODBUS_TEST_PORT})
    await asyncio.sleep(0.6)  # let the server bind

    # Build & start IntegrationManager pointed at the mocked EdgeLite
    event_bus = EventBus()
    manager = IntegrationManager(
        event_bus,
        enabled=True,
        edgelite_url=edgelite_url,
        username="admin",
        password="admin",
    )
    await manager.start()
    await asyncio.sleep(0.3)  # let login + protocol fetch complete

    yield engine, manager, edgelite_url, state, device

    await manager.stop()
    await engine.stop()
    await main_module._database.close()
    main_module._engine = None
    main_module._database = None
    main_module._log_bus = None
    _clear_registry()
    await runner.cleanup()


# ---------------------------------------------------------------------------
#  Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_convert_device_to_edgelite_produces_valid_payload(joint_env):
    """convert_device_to_edgelite must produce a complete EdgeLite device payload."""
    from protoforge.integrations.edgelite import convert_device_to_edgelite

    _engine, _mgr, edgelite_url, _state, device = joint_env
    el_config = {"url": edgelite_url, "username": "admin", "password": "admin"}

    result = convert_device_to_edgelite(device, el_config=el_config)

    assert result is not None, "Protocol modbus must be supported by EdgeLite"
    assert result["device_id"] == "e2e-edgelite-modbus"
    assert result["name"] == "E2E EdgeLite Modbus Device"
    # modbus → modbus_tcp plugin_name
    assert result["protocol"] in ("modbus", "modbus_tcp")
    assert isinstance(result["config"], dict)
    # Driver config must carry the connection target
    assert result["config"].get("host") == "127.0.0.1"
    assert result["config"].get("port") == MODBUS_TEST_PORT
    # Points must be translated
    assert len(result["points"]) >= 1
    pt = result["points"][0]
    assert pt["name"] == "temperature"
    assert "register_type" in pt or "address" in pt  # modbus points carry register info
    assert result["collect_interval"] == 5  # default


@pytest.mark.asyncio
async def test_push_device_to_mocked_edgelite_succeeds(joint_env):
    """push_device must register the device on EdgeLite and return ok=True."""
    _engine, manager, _url, state, device = joint_env

    result = await manager.push_device(device)

    assert result.get("ok") is True, f"push_device failed: {result}"
    assert result.get("action") in ("created", "updated")
    assert state.push_count >= 1, "Mocked EdgeLite did not receive a push request"
    # The pushed payload must carry the normalized device id
    pushed = state.pushed_payloads[-1]
    assert pushed["device_id"] == "e2e-edgelite-modbus"
    assert pushed["protocol"] in ("modbus", "modbus_tcp")


@pytest.mark.asyncio
async def test_verify_pipeline_all_steps_pass(joint_env):
    """verify_pipeline must pass all 4 steps when the device is online with data."""
    _engine, manager, _url, state, device = joint_env

    # Register the device on the mocked EdgeLite first (online + has data)
    push_result = await manager.push_device(device)
    assert push_result.get("ok") is True, f"pre-push failed: {push_result}"

    result = await manager.verify_pipeline(device, auto_fix=False)

    assert result.get("ok") is True, f"verify_pipeline should pass: {result}"
    steps = result["steps"]
    assert steps["auth"]["ok"] is True
    assert steps["register"]["ok"] is True
    assert steps["connect"]["ok"] is True
    assert steps["collect"]["ok"] is True
    assert steps["collect"].get("has_real_data") is True


@pytest.mark.asyncio
async def test_verify_pipeline_auto_fixes_unregistered_device(joint_env):
    """When the device is not registered, auto_fix must push it and then pass."""
    _engine, manager, _url, state, device = joint_env

    # Ensure the device is NOT registered on the mocked EdgeLite
    state.devices.pop("e2e-edgelite-modbus", None)
    push_before = state.push_count

    result = await manager.verify_pipeline(device, auto_fix=True)

    assert result.get("ok") is True, f"auto_fix verify_pipeline should pass: {result}"
    # auto_fix must have triggered a push
    assert state.push_count > push_before, "auto_fix did not push the unregistered device"
    # The register step should reflect the auto-fix
    assert result["steps"]["register"].get("auto_fixed") is True
    assert any(f["step"] == "register" for f in result.get("auto_fixes", []))


@pytest.mark.asyncio
async def test_verify_pipeline_detects_offline_device(joint_env):
    """When the device is offline on EdgeLite, verify_pipeline must report ok=False."""
    _engine, manager, _url, state, device = joint_env

    # Register the device first, then flip it to offline
    await manager.push_device(device)
    state.set_status("e2e-edgelite-modbus", "offline")

    result = await manager.verify_pipeline(device, auto_fix=False)

    assert result.get("ok") is False, "offline device should not pass verification"
    connect_step = result["steps"].get("connect", {})
    assert connect_step.get("ok") is False
    # The connect step must carry a human-readable error
    assert "error" in connect_step or "message" in connect_step or "detail" in connect_step
