"""Module: main."""

import logging
import logging.handlers
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI  # FIXED: 导入Depends用于/metrics认证
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from protoforge.api.v1.router import router
from protoforge.core.engine import SimulationEngine
from protoforge.core.event_bus import EventBus
from protoforge.core.integration.manager import IntegrationManager
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
    register_integration_manager as _register_integration_manager,
)
from protoforge.core.registry import (
    register_log_bus as _register_log_bus,
)
from protoforge.core.registry import (
    register_template_manager as _register_template_manager,
)
from protoforge.core.template import TemplateManager
from protoforge.db.session import Database
from protoforge.protocols import PROTOCOL_REGISTRY

logger = logging.getLogger(__name__)

# FIXED: 脱敏 uvicorn 访问日志中的 JWT token，避免敏感信息泄露到日志
class _TokenRedactingFilter(logging.Filter):
    _TOKEN_PATTERN = re.compile(r'token=eyJ[A-Za-z0-9_-]+')

    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            record.msg = self._TOKEN_PATTERN.sub('token=***', record.msg)
        if hasattr(record, 'args') and record.args:
            try:
                if isinstance(record.args, dict):
                    for k, v in record.args.items():
                        if isinstance(v, str):
                            record.args[k] = self._TOKEN_PATTERN.sub('token=***', v)
                elif isinstance(record.args, (tuple, list)):
                    record.args = tuple(
                        self._TOKEN_PATTERN.sub('token=***', a) if isinstance(a, str) else a
                        for a in record.args
                    )
            except Exception as e:
                logger.debug("Token redaction failed for log args: %s", e)
        return True


# 安装脱敏过滤器到 uvicorn 访问日志
for _uv_logger_name in ("uvicorn.access", "uvicorn.error"):
    _uv_logger = logging.getLogger(_uv_logger_name)
    _uv_logger.addFilter(_TokenRedactingFilter())

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


def _check_startup_security(settings: Any) -> None:
    """Log security warnings for insecure configuration on startup.

    Checks JWT secret, auth mode, admin password strength, CORS wildcard,
    and admin password reset flag. Non-blocking; only logs warnings.
    """
    _EXAMPLE_SECRET = ""
    try:
        _example_env = Path(__file__).resolve().parent.parent / ".env.example"
        if _example_env.exists():
            for _line in _example_env.read_text(encoding="utf-8").splitlines():
                if _line.strip().startswith("PROTOFORGE_JWT_SECRET="):
                    _EXAMPLE_SECRET = _line.strip().split("=", 1)[1].strip()
                    break
    except Exception as e:
        logger.debug("Failed to read .env.example for JWT secret check: %s", e)
    if not settings.jwt_secret or (_EXAMPLE_SECRET and settings.jwt_secret == _EXAMPLE_SECRET):
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
    if settings.reset_admin_password:
        logger.info(
            "CONFIG: PROTOFORGE_RESET_ADMIN_PASSWORD=true, admin password will be reset on startup. "
            "Remember to set it back to false after the password is changed."
        )
    if settings.cors_origins == "*":
        logger.warning(
            "SECURITY: CORS allows all origins (*). "
            "Set PROTOFORGE_CORS_ORIGINS to specific domain(s) for production."
        )


async def _init_core_services(settings: Any) -> tuple[Any, Any, Any, Any, Any, Any]:
    """Initialize and start all core services.

    Returns:
        Tuple of (engine, template_manager, database, log_bus, event_bus,
        integration_manager).
    """
    from protoforge.core.auth import set_secret_key

    set_secret_key(settings.jwt_secret)

    log_bus = LogBus()
    event_bus = EventBus()
    template_manager = TemplateManager()
    template_manager.load_builtin_templates()

    database = Database(db_path=settings.db_path)
    await database.connect()

    engine = SimulationEngine(event_bus=event_bus, tick_interval=getattr(settings, "tick_interval", 1.0))
    for protocol_cls in PROTOCOL_REGISTRY.values():
        engine.register_protocol(protocol_cls())
    engine.setup_debug_callbacks(log_bus)
    await engine.start()

    integration_manager = IntegrationManager(event_bus=event_bus)
    if settings.edgelite_url:
        integration_manager.configure(settings.edgelite_url, settings.edgelite_username, settings.edgelite_password)
    await integration_manager.start()

    return engine, template_manager, database, log_bus, event_bus, integration_manager


async def _restore_persisted_data(engine: Any, database: Any, template_manager: Any, settings: Any) -> list[str]:
    """Restore devices, scenarios, templates, and service state from database.

    Returns a list of error strings for components that failed to restore.
    """
    restore_errors: list[str] = []

    # Restore devices
    try:
        saved_devices = await database.load_all_devices()
        restored = 0
        for dev in saved_devices:
            try:
                if not dev.protocol_config:
                    dev.protocol_config = {}
                dev.protocol_config["_skip_auto_push"] = True
                await engine.create_device(dev, allow_update=True)
                dev.protocol_config.pop("_skip_auto_push", None)
                restored += 1
            except Exception as e:
                dev.protocol_config.pop("_skip_auto_push", None)
                logger.error("Failed to restore device %s: [%s] %s", dev.id, type(e).__name__, e)
        logger.info("Restored %d/%d devices from database", restored, len(saved_devices))
    except Exception as e:
        restore_errors.append(f"devices: {e}")
        logger.error("Failed to load devices from database: [%s] %s", type(e).__name__, e)

    # Restore scenarios
    try:
        saved_scenarios = await database.load_all_scenarios()
        for sc in saved_scenarios:
            try:
                await engine.create_scenario(sc)
            except Exception as e:
                logger.error("Failed to restore scenario %s: [%s] %s", sc.id, type(e).__name__, e)
        logger.info("Restored %d scenarios from database", len(saved_scenarios))
    except Exception as e:
        restore_errors.append(f"scenarios: {e}")
        logger.error("Failed to load scenarios from database: %s", e)

    # Restore templates
    try:
        saved_templates = await database.load_all_templates()
        for tmpl in saved_templates:
            try:
                template_manager.add_template(tmpl)
            except Exception as e:
                logger.error("Failed to restore template %s: [%s] %s", tmpl.id, type(e).__name__, e)
        logger.info("Restored %d templates from database", len(saved_templates))
    except Exception as e:
        restore_errors.append(f"templates: {e}")
        logger.error("Failed to load templates from database: %s", e)

    # Restore test data
    try:
        from protoforge.api.v1.test_routes import _get_test_runner
        runner = _get_test_runner()
        runner.set_database(database)
        await runner.restore_from_db()
        logger.info("Test data restored")
    except Exception as e:
        restore_errors.append(f"tests: {e}")
        logger.error("Failed to restore test data: %s", e)

    # Restore users
    try:
        from protoforge.core.auth import user_manager
        user_manager.set_database(database)
        await user_manager.restore_from_db()
        logger.info("Users restored")
    except Exception as e:
        restore_errors.append(f"users: {e}")
        logger.error("Failed to restore users: %s", e)

    # Start webhook manager
    try:
        from protoforge.core.webhook import webhook_manager
        await webhook_manager.start()
        logger.info("Webhook manager started")
    except Exception as e:
        restore_errors.append(f"webhooks: {e}")
        logger.error("Failed to start webhook manager: %s", e)

    # Initialize audit logger
    try:
        from protoforge.core.audit import audit_logger
        audit_logger.set_database(database)
        await audit_logger.restore_from_db()
        logger.info("Audit logger initialized")
    except Exception as e:
        restore_errors.append(f"audit: {e}")
        logger.error("Failed to initialize audit logger: %s", e)

    # Initialize recorder persistence
    try:
        from protoforge.api.v1.recorder_routes import _get_recorder
        recorder = _get_recorder()
        recorder.set_database(database)
        await recorder.restore_from_db()
        logger.info("Recorder persistence initialized")
    except Exception as e:
        restore_errors.append(f"recorder: {e}")
        logger.error("Failed to initialize recorder persistence: %s", e)

    # Start failover manager
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

    return restore_errors


async def _start_optional_services(engine: Any, template_manager: Any, settings: Any) -> Any:
    """Start demo data and gRPC server if configured.

    Returns the gRPC server instance (or None).
    """
    if settings.demo_mode:
        try:
            from protoforge.core.demo import seed_demo_data
            await seed_demo_data(engine, template_manager)
            logger.info("Demo data seeded")
        except Exception as e:
            logger.error("Failed to seed demo data: %s", e)

    grpc_server = None
    if settings.grpc_port > 0:
        try:
            from protoforge.grpc.server import start_grpc_server
            grpc_server = await start_grpc_server(settings.grpc_port)
        except Exception as e:
            logger.warning("Failed to start gRPC server: %s", e)

    return grpc_server


def _suppress_noisy_loggers() -> None:
    """Suppress verbose loggers from third-party libraries."""
    _deduplicate_file_handlers()
    logging.getLogger("asyncua").setLevel(logging.WARNING)
    for name in (
        "asyncua.client.ua_client.UASocketProtocol",
        "asyncua.client.ua_client.UaClient",
        "asyncua.client.client",
        "asyncua.server.binary_server_asyncio",
    ):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    logging.getLogger("amqtt.broker").setLevel(logging.CRITICAL)
    logging.getLogger("transitions.core").setLevel(logging.WARNING)


async def _run_schema_audit(database: Any) -> None:
    """Run schema audit to cross-check Pydantic models with DB columns."""
    try:
        from protoforge.audit.schema_audit import audit_schema
        schema_result = await audit_schema(database)
        if schema_result.ok:
            logger.info("Schema audit passed")
        else:
            logger.warning("Schema audit found issues:\n%s", schema_result.summary())
    except Exception as e:
        logger.warning("Schema audit failed (non-fatal): %s", e)


async def _shutdown_services(grpc_server: Any, integration_manager: Any, engine: Any, database: Any) -> None:
    """Gracefully shut down all services with timeout protection."""
    import asyncio

    async def _stop_with_timeout(coro, name, timeout=10):
        """Execute stop coroutine with timeout to prevent shutdown deadlock."""
        try:
            await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Timeout stopping %s (%ds), skipping", name, timeout)
        except Exception as e:
            logger.warning("Error stopping %s: %s", name, e)

    if grpc_server:
        await _stop_with_timeout(grpc_server.stop(grace=5), "gRPC server")

    await _stop_with_timeout(integration_manager.stop(), "integration manager")
    try:
        from protoforge.core.webhook import webhook_manager
        await _stop_with_timeout(webhook_manager.stop(), "webhook manager")
    except Exception as e:
        logger.warning("Error loading webhook manager: %s", e)
    await _stop_with_timeout(engine.stop(), "engine")
    await _stop_with_timeout(database.close(), "database")
    try:
        from protoforge.api.v1.test_routes import _close_internal_client
        await _stop_with_timeout(_close_internal_client(), "internal client", timeout=5)
    except Exception as e:
        logger.debug("Error loading internal client: %s", e)
    try:
        from protoforge.core.edgelite import _close_http_client
        await _stop_with_timeout(_close_http_client(), "HTTP client", timeout=5)
        logger.info("HTTP client closed")
    except Exception as e:
        logger.debug("Error loading HTTP client: %s", e)
    logger.info("ProtoForge stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup and shutdown."""
    global _engine, _template_manager, _database, _log_bus, _event_bus, _integration_manager

    from protoforge.config import get_settings
    settings = get_settings()

    _check_startup_security(settings)

    (_engine, _template_manager, _database, _log_bus, _event_bus,
     _integration_manager) = await _init_core_services(settings)

    # 注册服务到 ServiceRegistry，消除子模块对 main.py 的循环依赖
    _register_engine(_engine)
    _register_database(_database)
    _register_integration_manager(_integration_manager)
    _register_log_bus(_log_bus)
    _register_template_manager(_template_manager)

    restore_errors = await _restore_persisted_data(_engine, _database, _template_manager, settings)

    grpc_server = await _start_optional_services(_engine, _template_manager, settings)

    _suppress_noisy_loggers()

    await _run_schema_audit(_database)

    if restore_errors:
        logger.warning("ProtoForge started with %d restore error(s): %s", len(restore_errors), "; ".join(restore_errors))
    else:
        logger.info("ProtoForge started successfully")

    yield

    await _shutdown_services(grpc_server, _integration_manager, _engine, _database)

    # 注销所有服务，避免重启时状态残留
    _clear_registry()


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

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

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

        # FIXED: 扩展健康检查，包含各协议服务器的状态
        protocol_details = {}
        running_protocols = 0
        total_protocols = 0

        if _engine:
            for name, server in _engine.get_all_protocol_servers().items():
                status = server.status.value
                total_protocols += 1
                if status == "running":
                    running_protocols += 1
                protocol_details[name] = {
                    "status": status,
                    "display_name": getattr(server, 'protocol_display_name', name),
                }

        # 检查数据库连接健康
        db_health = "ok"
        if _database:
            try:
                if hasattr(_database, '_pool') and _database._pool:
                    # 检查连接池是否有可用连接
                    db_health = "ok"
            except Exception:
                db_health = "degraded"

        # FIXED-P1: 协议未启动不算degraded，仅当有协议处于error状态时才判定degraded
        has_error = any(d.get("status") == "error" for d in protocol_details.values())
        status = "ok" if (db_ok and engine_ok and not has_error) else "degraded"

        return {
            "status": status,
            "timestamp": int(time.time() * 1000),
            "database": db_ok,
            "database_health": db_health,
            "engine": engine_ok,
            "protocols": {
                "total": total_protocols,
                "running": running_protocols,
                "details": protocol_details,
            },
        }

    @app.get("/metrics", response_class=PlainTextResponse)
    @app.get("/api/v1/metrics", response_class=PlainTextResponse)
    async def prometheus_metrics(_user: dict[str, Any] = Depends(require_viewer)):  # FIXED: 添加认证保护，防止内部指标泄露
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
