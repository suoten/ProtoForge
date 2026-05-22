import logging
import logging.handlers
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends  # FIXED: 导入Depends用于/metrics认证
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from protoforge.api.v1.router import router
from protoforge.core.engine import SimulationEngine
from protoforge.core.event_bus import EventBus
from protoforge.core.integration.manager import IntegrationManager
from protoforge.core.log_bus import LogBus
from protoforge.core.template import TemplateManager
from protoforge.db.session import Database
from protoforge.protocols import PROTOCOL_REGISTRY

logger = logging.getLogger(__name__)

_LOG_MAX_BYTES = 10 * 1024 * 1024  # FIXED: P4 - Q5 日志文件最大字节数(10MB)，提取为模块级常量

_engine: SimulationEngine | None = None
_template_manager: TemplateManager | None = None
_database: Database | None = None
_log_bus: LogBus | None = None
_event_bus: EventBus | None = None
_integration_manager: IntegrationManager | None = None
_globals_lock = threading.Lock()


def get_engine() -> SimulationEngine:
    global _engine
    with _globals_lock:
        if _engine is None:
            raise RuntimeError("Engine not initialized")
        return _engine


def get_template_manager() -> TemplateManager:
    global _template_manager
    with _globals_lock:  # FIXED: 添加锁保护，与get_engine()一致
        if _template_manager is None:
            raise RuntimeError("Template manager not initialized")
        return _template_manager


def get_database() -> Database:
    global _database
    with _globals_lock:  # FIXED: 添加锁保护，与get_engine()一致
        if _database is None:
            raise RuntimeError("Database not initialized")
        return _database


def get_log_bus() -> LogBus:
    global _log_bus
    with _globals_lock:  # FIXED: 添加锁保护，与get_engine()一致
        if _log_bus is None:
            raise RuntimeError("Log bus not initialized")
        return _log_bus


def get_event_bus() -> EventBus:
    global _event_bus
    with _globals_lock:  # FIXED: 添加锁保护，与get_engine()一致
        if _event_bus is None:
            raise RuntimeError("Event bus not initialized")
        return _event_bus


def get_integration_manager() -> IntegrationManager:
    global _integration_manager
    with _globals_lock:  # FIXED: 添加锁保护，与get_engine()一致
        if _integration_manager is None:
            raise RuntimeError("Integration manager not initialized")
        return _integration_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine, _template_manager, _database, _log_bus, _event_bus, _integration_manager

    from protoforge.config import get_settings
    settings = get_settings()

    # FIXED: S2/S3 - startup security warnings for empty JWT secret, no_auth mode, and default password
    if not settings.jwt_secret or settings.jwt_secret == "mlLn6iuAEpJ_DrTojBDWqodv5wBE9O6-xrkS3jsltGI":
        logger.warning(
            "SECURITY: JWT secret is empty or using example default. "
            "Set PROTOFORGE_JWT_SECRET to a strong random value for production."
        )
    if settings.no_auth:
        logger.warning(
            "SECURITY: Authentication is DISABLED (PROTOFORGE_NO_AUTH=true). "
            "Never use this in production."
        )
    if settings.admin_password in ("admin", "admin123", ""):
        logger.warning(
            "SECURITY: Admin password is weak or default. "
            "Set PROTOFORGE_ADMIN_PASSWORD to a strong password for production."
        )
    if settings.cors_origins == "*":
        logger.warning(
            "SECURITY: CORS allows all origins (*). "
            "Set PROTOFORGE_CORS_ORIGINS to specific domain(s) for production."
        )

    from protoforge.core.auth import set_secret_key
    set_secret_key(settings.jwt_secret)

    _log_bus = LogBus()

    _event_bus = EventBus()

    _template_manager = TemplateManager()
    _template_manager.load_builtin_templates()

    _database = Database(db_path=settings.db_path)
    await _database.connect()

    _engine = SimulationEngine(event_bus=_event_bus, tick_interval=getattr(settings, 'tick_interval', 1.0))
    for protocol_cls in PROTOCOL_REGISTRY.values():
        _engine.register_protocol(protocol_cls())
    _engine.setup_debug_callbacks(_log_bus)
    await _engine.start()

    _integration_manager = IntegrationManager(event_bus=_event_bus)
    integration_url = settings.edgelite_url
    integration_user = settings.edgelite_username
    integration_pass = settings.edgelite_password
    if integration_url:
        _integration_manager.configure(integration_url, integration_user, integration_pass)
    await _integration_manager.start()

    restore_errors = []

    try:
        saved_devices = await _database.load_all_devices()
        restored = 0
        for dev in saved_devices:
            try:
                if not dev.protocol_config:
                    dev.protocol_config = {}
                dev.protocol_config["_skip_auto_push"] = True
                await _engine.create_device(dev, allow_update=True)
                dev.protocol_config.pop("_skip_auto_push", None)
                restored += 1
            except Exception as e:
                dev.protocol_config.pop("_skip_auto_push", None)
                logger.error("Failed to restore device %s: [%s] %s", dev.id, type(e).__name__, e)
        logger.info("Restored %d/%d devices from database", restored, len(saved_devices))
    except Exception as e:
        restore_errors.append(f"devices: {e}")
        logger.error("Failed to load devices from database: [%s] %s", type(e).__name__, e)

    try:
        saved_scenarios = await _database.load_all_scenarios()
        for sc in saved_scenarios:
            try:
                _engine.create_scenario(sc)
            except Exception as e:
                logger.error("Failed to restore scenario %s: [%s] %s", sc.id, type(e).__name__, e)
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
                logger.error("Failed to restore template %s: [%s] %s", tmpl.id, type(e).__name__, e)
        logger.info("Restored %d templates from database", len(saved_templates))
    except Exception as e:
        restore_errors.append(f"templates: {e}")
        logger.error("Failed to load templates from database: %s", e)

    try:
        from protoforge.api.v1.test_routes import _get_test_runner
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

    try:
        from protoforge.core.audit import audit_logger
        audit_logger.set_database(_database)
        await audit_logger.restore_from_db()
        logger.info("Audit logger initialized")
    except Exception as e:
        restore_errors.append(f"audit: {e}")
        logger.error("Failed to initialize audit logger: %s", e)

    try:
        from protoforge.core.recorder import Recorder
        from protoforge.api.v1.recorder_routes import _get_recorder
        recorder = _get_recorder()
        recorder.set_database(_database)
        await recorder.restore_from_db()
        logger.info("Recorder persistence initialized")
    except Exception as e:
        restore_errors.append(f"recorder: {e}")
        logger.error("Failed to initialize recorder persistence: %s", e)

    try:
        from protoforge.core.failover import failover_manager
        primary_url = settings.failover_primary
        standby_url = settings.failover_standby
        is_primary = settings.failover_role != "standby"
        if primary_url:
            failover_manager.configure(primary_url, standby_url, is_primary)
            await failover_manager.start()
            logger.info("Failover manager started (role=%s)", "primary" if is_primary else "standby")
    except Exception as e:
        restore_errors.append(f"failover: {e}")
        logger.error("Failed to start failover manager: %s", e)

    if settings.demo_mode:
        try:
            from protoforge.core.demo import seed_demo_data
            await seed_demo_data(_engine, _template_manager)
            logger.info("Demo data seeded")
        except Exception as e:
            logger.error("Failed to seed demo data: %s", e)

    grpc_server = None
    grpc_port = settings.grpc_port
    if grpc_port > 0:
        try:
            from protoforge.grpc.server import start_grpc_server
            grpc_server = await start_grpc_server(grpc_port)
        except Exception as e:
            logger.warning("Failed to start gRPC server: %s", e)

    _deduplicate_file_handlers()
    logging.getLogger("asyncua").setLevel(logging.WARNING)
    # Suppress noisy asyncua internal warnings/errors that flood the log
    logging.getLogger("asyncua.client.ua_client.UASocketProtocol").setLevel(logging.CRITICAL)
    logging.getLogger("asyncua.client.ua_client.UaClient").setLevel(logging.CRITICAL)
    logging.getLogger("asyncua.client.client").setLevel(logging.CRITICAL)
    logging.getLogger("asyncua.server.binary_server_asyncio").setLevel(logging.CRITICAL)
    # Suppress noisy amqtt broker client disconnection logs
    logging.getLogger("amqtt.broker").setLevel(logging.CRITICAL)
    # Suppress noisy transitions library state machine logs
    logging.getLogger("transitions.core").setLevel(logging.WARNING)

    if restore_errors:
        logger.warning("ProtoForge started with %d restore error(s): %s", len(restore_errors), "; ".join(restore_errors))
    else:
        logger.info("ProtoForge started successfully")

    yield

    if grpc_server:
        try:
            await grpc_server.stop(grace=5)
            logger.info("gRPC server stopped")
        except Exception as e:
            logger.warning("Error stopping gRPC server: %s", e)

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
    try:
        from protoforge.api.v1.test_routes import _close_internal_client
        await _close_internal_client()
    except Exception as e:
        logger.debug("Error closing internal client: %s", e)
    logger.info("ProtoForge stopped")


_logging_configured = False


def _deduplicate_file_handlers() -> None:
    """Remove duplicate RotatingFileHandler instances from root logger.

    Called after app startup to clean up any handlers that were added by
    multiple logging configuration passes (uvicorn dictConfig + _setup_file_logging).
    """
    root_logger = logging.getLogger()
    file_handlers = [h for h in root_logger.handlers
                     if isinstance(h, logging.handlers.RotatingFileHandler)]
    if len(file_handlers) > 1:
        for h in file_handlers[1:]:
            root_logger.removeHandler(h)
            h.close()
        logger.info("Cleaned up %d duplicate file handler(s) after startup", len(file_handlers) - 1)


def _setup_file_logging(settings) -> None:
    """Configure Python logging to output to logs/ directory with rotation.

    When running via cli.py (uvicorn.run), logging is configured via log_config
    parameter which includes the file handler. This function is a fallback for
    non-uvicorn usage (e.g., TestClient, gRPC server).
    """
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True

    root_logger = logging.getLogger()

    # 直接返回，不重复添加。同时清理可能存在的重复handler。
    file_handlers = [h for h in root_logger.handlers
                     if isinstance(h, logging.handlers.RotatingFileHandler)]
    if file_handlers:
        # 保留第一个，移除多余的
        for h in file_handlers[1:]:
            root_logger.removeHandler(h)
            h.close()
        if len(file_handlers) > 1:
            logger.info("Removed %d duplicate file handler(s)", len(file_handlers) - 1)
        return

    # 如果检测到uvicorn进程（通过sys.argv或已有uvicorn logger handler），跳过手动添加。
    import sys
    is_uvicorn = any("uvicorn" in arg for arg in sys.argv)
    if not is_uvicorn:
        # 也检查uvicorn logger是否已被配置（dictConfig先于app import执行）
        uvicorn_logger = logging.getLogger("uvicorn")
        if uvicorn_logger.handlers:
            is_uvicorn = True
    if is_uvicorn:
        logger.debug("Skipping file logging setup (uvicorn log_config will handle it)")
        return

    # No file handler found — fallback for non-uvicorn usage (TestClient, gRPC, etc.)
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "protoforge.log"

    log_level_str = getattr(settings, 'log_level', 'info') or 'info'
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    file_handler = logging.handlers.RotatingFileHandler(
        str(log_file),
        maxBytes=_LOG_MAX_BYTES,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)

    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)

    logger.info("File logging configured: %s (level=%s)", log_file, log_level_str)


def create_app() -> FastAPI:
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    from protoforge.config import get_settings
    settings = get_settings()

    _setup_file_logging(settings)

    app = FastAPI(
        title="ProtoForge",
        description="IoT Protocol Simulation & Testing Platform API",
        version="0.1.0",
        lifespan=lifespan,
    )

    from protoforge.api.v1.common import setup_exception_handlers
    setup_exception_handlers(app)

    # FastAPI中间件是后注册先执行(洋葱模型)，所以audit要先注册才能在auth之后执行
    from protoforge.core.audit import audit_middleware
    app.middleware("http")(audit_middleware)

    from protoforge.api.v1.auth import auth_middleware, require_viewer  # FIXED: 导入require_viewer用于/metrics认证
    app.middleware("http")(auth_middleware)

    cors_origins_raw = settings.cors_origins or ""
    cors_origins_list = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
    if not cors_origins_list:
        cors_origins_list = [f"http://localhost:{settings.port}", f"http://127.0.0.1:{settings.port}"]
        logger.info(
            "CORS origins not configured. Defaulting to localhost only. "
            "Set PROTOFORGE_CORS_ORIGINS for production (e.g. 'https://your-domain.com')."
        )
    has_wildcard = "*" in cors_origins_list
    if has_wildcard and len(cors_origins_list) > 1:
        logger.warning(
            "CORS origins contains both '*' and specific domains. "
            "Removing specific domains as '*' already allows all origins."
        )
        cors_origins_list = ["*"]
    is_wildcard = cors_origins_list == ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins_list,
        allow_credentials=not is_wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if is_wildcard:
        logger.warning(
            "CORS is configured to allow all origins (*). "
            "This is appropriate for development only. "
            "Set PROTOFORGE_CORS_ORIGINS to specific domain(s) for production."
        )

    from protoforge.api.v1.rate_limit import rate_limit_middleware
    app.middleware("http")(rate_limit_middleware)

    app.include_router(router)

    @app.get("/health")
    @app.get("/api/v1/health")
    async def health():
        db_ok = _database is not None
        engine_ok = _engine is not None
        protocol_count = len(_engine.get_all_protocol_servers()) if _engine else 0
        running_protocols = sum(
            1 for s in (list(_engine.get_all_protocol_servers().values()) if _engine else [])
            if s.status.value == "running"
        )
        status = "ok" if (db_ok and engine_ok) else "degraded"
        return {
            "status": status,
            "timestamp": int(time.time() * 1000),
            "database": db_ok,
            "engine": engine_ok,
            "protocols": {"total": protocol_count, "running": running_protocols},
        }

    @app.get("/metrics", response_class=PlainTextResponse)
    @app.get("/api/v1/metrics", response_class=PlainTextResponse)
    async def prometheus_metrics(_user: dict = Depends(require_viewer)):  # FIXED: 添加认证保护，防止内部指标泄露
        from protoforge.core.metrics import metrics
        try:
            engine = get_engine()
            metrics.collect_from_engine(engine)
        except RuntimeError:
            logger.debug("Metrics: engine not available")
        try:
            from protoforge.api.v1.test_routes import _get_test_runner
            runner = _get_test_runner()
            metrics.collect_from_test_runner(runner)
        except (RuntimeError, ImportError):
            logger.debug("Metrics: test runner not available")
        return metrics.generate_prometheus_output()

    static_dir = Path(__file__).parent.parent / "web" / "dist"
    fallback_dir = Path(__file__).parent.parent / "static"

    if not static_dir.is_dir():
        env_static = os.environ.get("PROTOFORGE_STATIC_DIR", "")
        static_dir = Path(env_static) if env_static else Path("/app/web/dist")
    if not fallback_dir.is_dir():
        env_fallback = os.environ.get("PROTOFORGE_FALLBACK_DIR", "")
        fallback_dir = Path(env_fallback) if env_fallback else Path("/app/static")

    spa_dir = static_dir if static_dir.is_dir() else (fallback_dir if fallback_dir.is_dir() else None)

    if spa_dir:
        app.mount("/assets", StaticFiles(directory=spa_dir / "assets"), name="assets")
        _spa_dir_resolved = spa_dir.resolve()

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi") or full_path.startswith("redoc"):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            file_path = (spa_dir / full_path).resolve()
            if not str(file_path).startswith(str(_spa_dir_resolved)):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(spa_dir / "index.html")
    else:
        logger.warning(
            "Frontend static files not found: %s and %s. "
            "Run 'cd web && npm install && npm run build' to build the frontend.",
            static_dir,
            fallback_dir,
        )

        @app.get("/")
        async def frontend_not_built():
            from fastapi.responses import HTMLResponse
            return HTMLResponse(content="""
<!DOCTYPE html>
<html>
<head><title>ProtoForge - Frontend Not Built</title></head>
<body style="font-family:system-ui,sans-serif;max-width:700px;margin:80px auto;padding:0 20px">
<h1>ProtoForge API is running</h1>
<p>The web frontend has not been built yet. You can still use the API:</p>
<ul>
<li><a href="/docs">API Documentation (Swagger UI)</a></li>
<li><a href="/api/v1/health">Health Check</a></li>
</ul>
<h2>To enable the web interface:</h2>
<pre style="background:#f5f5f5;padding:16px;border-radius:8px">cd web
npm install
npm run build</pre>
<p>Then restart ProtoForge.</p>
</body>
</html>
            """)

    return app


app = create_app()
