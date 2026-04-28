import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from protoforge.api.v1.router import router
from protoforge.core.engine import SimulationEngine
from protoforge.core.event_bus import EventBus
from protoforge.core.integration.manager import IntegrationManager
from protoforge.core.log_bus import LogBus
from protoforge.core.template import TemplateManager
from protoforge.db.session import Database
from protoforge.protocols.http.server import HttpSimulatorServer
from protoforge.protocols.modbus.server import ModbusTcpServer
from protoforge.protocols.modbus.rtu_server import ModbusRtuServer
from protoforge.protocols.mqtt.server import MqttBroker
from protoforge.protocols.opcua.server import OpcUaServer
from protoforge.protocols.gb28181.server import GB28181Server
from protoforge.protocols.bacnet.server import BACnetServer
from protoforge.protocols.s7.server import S7Server
from protoforge.protocols.mc.server import McServer
from protoforge.protocols.fins.server import FinsServer
from protoforge.protocols.ab.server import AbServer
from protoforge.protocols.opcda.server import OpcDaServer
from protoforge.protocols.fanuc.server import FanucServer
from protoforge.protocols.mtconnect.server import MtConnectServer
from protoforge.protocols.toledo.server import ToledoServer
from protoforge.protocols.profinet.server import ProfinetServer
from protoforge.protocols.ethercat.server import EtherCATServer

logger = logging.getLogger(__name__)

_engine: SimulationEngine | None = None
_template_manager: TemplateManager | None = None
_database: Database | None = None
_log_bus: LogBus | None = None
_event_bus: EventBus | None = None
_integration_manager: IntegrationManager | None = None


def get_engine() -> SimulationEngine:
    global _engine
    if _engine is None:
        raise RuntimeError("Engine not initialized")
    return _engine


def get_template_manager() -> TemplateManager:
    global _template_manager
    if _template_manager is None:
        raise RuntimeError("Template manager not initialized")
    return _template_manager


def get_database() -> Database:
    global _database
    if _database is None:
        raise RuntimeError("Database not initialized")
    return _database


def get_log_bus() -> LogBus:
    global _log_bus
    if _log_bus is None:
        raise RuntimeError("Log bus not initialized")
    return _log_bus


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        raise RuntimeError("Event bus not initialized")
    return _event_bus


def get_integration_manager() -> IntegrationManager:
    global _integration_manager
    if _integration_manager is None:
        raise RuntimeError("Integration manager not initialized")
    return _integration_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine, _template_manager, _database, _log_bus, _event_bus, _integration_manager

    from protoforge.config import get_settings
    settings = get_settings()

    from protoforge.core.auth import set_secret_key
    set_secret_key(settings.jwt_secret)

    _log_bus = LogBus()

    _event_bus = EventBus()

    _template_manager = TemplateManager()
    _template_manager.load_builtin_templates()

    _database = Database()
    await _database.connect()

    _engine = SimulationEngine(event_bus=_event_bus)
    _engine.register_protocol(ModbusTcpServer())
    _engine.register_protocol(ModbusRtuServer())
    _engine.register_protocol(OpcUaServer())
    _engine.register_protocol(MqttBroker())
    _engine.register_protocol(HttpSimulatorServer())
    _engine.register_protocol(GB28181Server())
    _engine.register_protocol(BACnetServer())
    _engine.register_protocol(S7Server())
    _engine.register_protocol(McServer())
    _engine.register_protocol(FinsServer())
    _engine.register_protocol(AbServer())
    _engine.register_protocol(OpcDaServer())
    _engine.register_protocol(FanucServer())
    _engine.register_protocol(MtConnectServer())
    _engine.register_protocol(ToledoServer())
    _engine.register_protocol(ProfinetServer())
    _engine.register_protocol(EtherCATServer())
    _engine.setup_debug_callbacks(_log_bus)
    await _engine.start()

    _integration_manager = IntegrationManager(event_bus=_event_bus)
    import os
    integration_url = os.environ.get("PROTOFORGE_INTEGRATION_EDGELITE_URL", "")
    integration_user = os.environ.get("PROTOFORGE_INTEGRATION_EDGELITE_USERNAME", "admin")
    integration_pass = os.environ.get("PROTOFORGE_INTEGRATION_EDGELITE_PASSWORD", "")
    if integration_url:
        _integration_manager.configure(integration_url, integration_user, integration_pass)
    await _integration_manager.start()

    restore_errors = []

    try:
        saved_devices = await _database.load_all_devices()
        restored = 0
        for dev in saved_devices:
            try:
                await _engine.create_device(dev)
                restored += 1
            except Exception as e:
                logger.error("Failed to restore device %s: %s", dev.id, e)
        logger.info("Restored %d/%d devices from database", restored, len(saved_devices))
    except Exception as e:
        restore_errors.append(f"devices: {e}")
        logger.error("Failed to load devices from database: %s", e)

    try:
        saved_scenarios = await _database.load_all_scenarios()
        for sc in saved_scenarios:
            try:
                _engine.create_scenario(sc)
            except Exception as e:
                logger.error("Failed to restore scenario %s: %s", sc.id, e)
        logger.info("Restored %d scenarios from database", len(saved_scenarios))
    except Exception as e:
        restore_errors.append(f"scenarios: {e}")
        logger.error("Failed to load scenarios from database: %s", e)

    try:
        saved_templates = await _database.load_all_templates()
        for tmpl in saved_templates:
            try:
                _template_manager.add_template(tmpl)
            except Exception as e:
                logger.error("Failed to restore template %s: %s", tmpl.id, e)
        logger.info("Restored %d templates from database", len(saved_templates))
    except Exception as e:
        restore_errors.append(f"templates: {e}")
        logger.error("Failed to load templates from database: %s", e)

    try:
        from protoforge.api.v1.router import _get_test_runner
        runner = _get_test_runner()
        runner.set_database(_database)
        await runner.restore_from_db()
        logger.info("Test data restored")
    except Exception as e:
        restore_errors.append(f"tests: {e}")
        logger.error("Failed to restore test data: %s", e)

    try:
        from protoforge.core.auth import user_manager
        user_manager.set_database(_database)
        await user_manager.restore_from_db()
        logger.info("Users restored")
    except Exception as e:
        restore_errors.append(f"users: {e}")
        logger.error("Failed to restore users: %s", e)

    try:
        from protoforge.core.webhook import webhook_manager
        await webhook_manager.start()
        logger.info("Webhook manager started")
    except Exception as e:
        restore_errors.append(f"webhooks: {e}")
        logger.error("Failed to start webhook manager: %s", e)

    import os
    if os.environ.get("PROTOFORGE_DEMO_MODE"):
        try:
            from protoforge.core.demo import seed_demo_data
            await seed_demo_data(_engine, _template_manager)
            logger.info("Demo data seeded")
        except Exception as e:
            logger.error("Failed to seed demo data: %s", e)

    if restore_errors:
        logger.warning("ProtoForge started with %d restore error(s): %s", len(restore_errors), "; ".join(restore_errors))
    else:
        logger.info("ProtoForge started successfully")

    yield

    try:
        await _integration_manager.stop()
    except Exception as e:
        logger.warning("Error stopping integration manager: %s", e)
    try:
        from protoforge.core.webhook import webhook_manager
        await webhook_manager.stop()
    except Exception as e:
        logger.warning("Error stopping webhook manager: %s", e)
    try:
        await _engine.stop()
    except Exception as e:
        logger.error("Error stopping engine: %s", e)
    try:
        await _database.close()
    except Exception as e:
        logger.error("Error closing database: %s", e)
    logger.info("ProtoForge stopped")


def create_app() -> FastAPI:
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    app = FastAPI(
        title="ProtoForge",
        description="物联网协议仿真与测试平台 API",
        version="0.1.0",
        lifespan=lifespan,
    )

    from protoforge.api.v1.common import setup_exception_handlers
    setup_exception_handlers(app)

    from protoforge.api.v1.rate_limit import rate_limit_middleware
    app.middleware("http")(rate_limit_middleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from protoforge.api.v1.auth import auth_middleware
    app.middleware("http")(auth_middleware)

    app.include_router(router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "timestamp": int(time.time() * 1000)}

    static_dir = Path(__file__).parent.parent / "web" / "dist"
    if not static_dir.is_dir():
        static_dir = Path(__file__).parent.parent / "static"
    if static_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi") or full_path.startswith("redoc"):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            file_path = static_dir / full_path
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
