"""Shared test fixtures and configuration for ProtoForge test suite."""

import os
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# Disable auth by default for testing; use the 'auth_enabled' fixture to opt-in
os.environ["PROTOFORGE_NO_AUTH"] = "1"
os.environ.setdefault("PROTOFORGE_TEST_MODE", "1")

# Track original auth state so the auth_enabled fixture can restore it
_original_no_auth = os.environ.get("PROTOFORGE_NO_AUTH", "1")

collect_ignore_glob = ["*/testing.py"]


@pytest.fixture(autouse=True)
def _ensure_no_auth():
    """Ensure auth is disabled for every test unless auth_enabled is used."""
    os.environ["PROTOFORGE_NO_AUTH"] = "1"
    # Reset cached settings so is_no_auth() picks up the env var
    import protoforge.config as cfg
    old = cfg._settings
    cfg._settings = None
    # Reset auth module warning flag
    from protoforge.api.v1 import auth as auth_module
    auth_module._no_auth_warning_shown = False
    yield
    cfg._settings = old


# ---------------------------------------------------------------------------
# Core service fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def log_bus():
    """Provide a fresh LogBus instance."""
    from protoforge.core.log_bus import LogBus
    return LogBus()


@pytest.fixture
def template_manager():
    """Provide a TemplateManager with built-in templates loaded."""
    from protoforge.core.template import TemplateManager
    tm = TemplateManager()
    tm.load_builtin_templates()
    return tm


@pytest_asyncio.fixture
async def database():
    """Provide a connected in-memory database, cleaned up after test."""
    from protoforge.db.session import Database
    db = Database()
    await db.connect()
    try:
        yield db
    finally:
        await db.close()


@pytest_asyncio.fixture
async def engine():
    """Provide a started SimulationEngine with common protocols, cleaned up after test."""
    from protoforge.core.engine import SimulationEngine
    from protoforge.protocols.http.server import HttpSimulatorServer
    from protoforge.protocols.modbus.server import ModbusTcpServer

    eng = SimulationEngine()
    eng.register_protocol(ModbusTcpServer())
    eng.register_protocol(HttpSimulatorServer())
    await eng.start()
    try:
        yield eng
    finally:
        await eng.stop()


# ---------------------------------------------------------------------------
# Auth-enabled testing fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_enabled(monkeypatch):
    """Enable authentication for tests that need to verify auth/authorization.

    Usage::

        async def test_login_with_auth(auth_enabled, client):
            resp = await client.post("/api/v1/auth/login", json={...})
            assert resp.status_code == 200
    """
    monkeypatch.setenv("PROTOFORGE_NO_AUTH", "0")
    # Reset cached settings so is_no_auth() picks up the env var change
    import protoforge.config as cfg
    old_settings = cfg._settings
    cfg._settings = None
    # Re-evaluate the auth flag in the auth module
    from protoforge.api.v1 import auth as auth_module
    auth_module._no_auth_warning_shown = False
    yield
    monkeypatch.setenv("PROTOFORGE_NO_AUTH", _original_no_auth)
    cfg._settings = old_settings
    auth_module._no_auth_warning_shown = False


# ---------------------------------------------------------------------------
# Full application client fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client() -> AsyncIterator:
    """Provide an async HTTP client backed by the ASGI app.

    This fixture sets up the full application stack including engine,
    database, template manager, and log bus. It is shared across all
    test modules that need API access.
    """
    from httpx import ASGITransport, AsyncClient

    import protoforge.main as main_module
    from protoforge.core.engine import SimulationEngine
    from protoforge.core.log_bus import LogBus
    from protoforge.core.registry import (
        clear_all as _clear_registry,
    )
    from protoforge.core.registry import (
        register_database as _register_database,
    )
    from protoforge.core.registry import (
        register_engine as _register_engine,
    )
    from protoforge.core.registry import (
        register_log_bus as _register_log_bus,
    )
    from protoforge.core.registry import (
        register_template_manager as _register_template_manager,
    )
    from protoforge.core.template import TemplateManager
    from protoforge.protocols.bacnet.server import BACnetServer
    from protoforge.protocols.http.server import HttpSimulatorServer
    from protoforge.protocols.modbus.server import ModbusTcpServer
    from protoforge.protocols.s7.server import S7Server

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

    _register_engine(main_module._engine)
    _register_database(main_module._database)
    _register_log_bus(main_module._log_bus)
    _register_template_manager(main_module._template_manager)

    transport = ASGITransport(app=main_module.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await main_module._engine.stop()
    await main_module._database.close()

    main_module._engine = None
    main_module._template_manager = None
    main_module._database = None
    main_module._log_bus = None
    _clear_registry()


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_device_config():
    """Provide a factory for device configurations."""
    def _make(
        device_id: str = "mock-device-001",
        protocol: str = "modbus_tcp",
        name: str = "mock-sensor",
        points: list | None = None,
    ):
        if points is None:
            points = [
                {
                    "name": "temperature",
                    "address": "0",
                    "data_type": "float32",
                    "unit": "C",
                    "generator_type": "random",
                    "min_value": 15.0,
                    "max_value": 35.0,
                }
            ]
        return {
            "id": device_id,
            "name": name,
            "protocol": protocol,
            "points": points,
        }
    return _make


@pytest.fixture
def mock_scenario_config():
    """Provide a factory for scenario configurations."""
    def _make(
        scenario_id: str = "mock-scenario-001",
        name: str = "mock-scenario",
        devices: list | None = None,
        rules: list | None = None,
    ):
        return {
            "id": scenario_id,
            "name": name,
            "description": "mock scenario for testing",
            "devices": devices or [],
            "rules": rules or [],
        }
    return _make


@pytest.fixture
def make_mock_protocol_server():
    """Provide a factory for mock protocol servers."""
    def _make(protocol_name: str = "mock_protocol"):
        server = MagicMock()
        server.protocol_name = protocol_name
        server.protocol_display_name = protocol_name.upper()
        server.start = AsyncMock()
        server.stop = AsyncMock()
        server.is_running = False
        server.get_status = MagicMock(return_value={"running": False})
        server.list_devices = MagicMock(return_value=[])
        return server
    return _make
