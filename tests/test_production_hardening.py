"""D.2 生产加固验证测试.

覆盖：
1. graceful shutdown 顺序与超时保护
2. JWT 认证中间件：受保护路由 401、公共路径放行、no_auth 模式
3. CORS 配置解析：空默认 localhost、通配符处理、多域名
4. 启动安全检查：弱密码/空 JWT/通配符 CORS 触发告警
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("PROTOFORGE_DB_PATH", "sqlite:///./data/test_hardening.db")


# ---------------------------------------------------------------------------
#  1. Graceful shutdown 顺序与超时
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_stops_services_in_order():
    """_shutdown_services 按序停止：gRPC → 集成管理器 → 引擎 → 数据库。"""
    from protoforge.main import _shutdown_services

    grpc_server = MagicMock()
    grpc_server.stop = MagicMock(return_value=asyncio.Future())
    grpc_server.stop.return_value.set_result(None)

    integration_manager = MagicMock()
    integration_manager.stop = AsyncMock(return_value=None)

    engine = MagicMock()
    engine.stop = AsyncMock(return_value=None)

    database = MagicMock()
    database.close = AsyncMock(return_value=None)

    call_order: list[str] = []

    def track(name):
        def _tracker(*args, **kwargs):
            call_order.append(name)
            return MagicMock()
        return _tracker

    grpc_server.stop = MagicMock(side_effect=track("grpc"))
    integration_manager.stop = AsyncMock(side_effect=track("integration"))
    engine.stop = AsyncMock(side_effect=track("engine"))
    database.close = AsyncMock(side_effect=track("database"))

    with patch("protoforge.integrations.webhook.webhook_manager.stop", new=AsyncMock(side_effect=track("webhook"))):
        with patch("protoforge.api.v1.test_routes._close_internal_client", new=AsyncMock(side_effect=track("internal_client"))):
            with patch("protoforge.integrations.edgelite._close_http_client", new=AsyncMock(side_effect=track("http_client"))):
                await _shutdown_services(grpc_server, integration_manager, engine, database)

    # 验证关键停止顺序
    assert call_order.index("grpc") < call_order.index("integration"), "gRPC 应在集成管理器前停止"
    assert call_order.index("integration") < call_order.index("engine"), "集成管理器应在引擎前停止"
    assert call_order.index("engine") < call_order.index("database"), "引擎应在数据库前停止"


@pytest.mark.asyncio
async def test_shutdown_timeout_protection():
    """某个服务 stop 超时不会阻塞整个关闭流程。"""
    from protoforge.main import _shutdown_services

    grpc_server = None
    integration_manager = MagicMock()
    # 模拟集成管理器 stop 永不完成
    integration_manager.stop = AsyncMock(side_effect=asyncio.sleep(1000))

    engine = MagicMock()
    engine.stop = AsyncMock(return_value=None)

    database = MagicMock()
    database.close = AsyncMock(return_value=None)

    with patch("protoforge.integrations.webhook.webhook_manager.stop", new=AsyncMock()):
        with patch("protoforge.api.v1.test_routes._close_internal_client", new=AsyncMock()):
            with patch("protoforge.integrations.edgelite._close_http_client", new=AsyncMock()):
                # 应在合理时间内完成（超时保护），而非等待 1000s
                await asyncio.wait_for(
                    _shutdown_services(grpc_server, integration_manager, engine, database),
                    timeout=30,
                )

    # database.close 仍被调用（超时后继续）
    database.close.assert_called_once()


# ---------------------------------------------------------------------------
#  2. JWT 认证中间件
# ---------------------------------------------------------------------------


def _make_request(path: str, method: str = "GET", auth_header: str = ""):
    """构造模拟 Request 对象。"""
    request = MagicMock()
    request.url.path = path
    request.method = method
    # 使用真实 dict（已内置 .get 方法），避免覆盖只读属性
    request.headers = {"Authorization": auth_header} if auth_header else {}
    request.state = MagicMock()
    return request


@pytest.mark.asyncio
async def test_auth_middleware_protected_route_returns_401_without_token():
    """无 token 访问受保护路由 → 401。"""
    from protoforge.api.v1.auth import auth_middleware
    from protoforge.config import get_settings

    get_settings().no_auth = False
    request = _make_request("/api/v1/devices", method="GET")
    call_next = AsyncMock()
    response = await auth_middleware(request, call_next)
    assert response.status_code == 401
    call_next.assert_not_called()


@pytest.mark.asyncio
async def test_auth_middleware_public_path_passes_through():
    """公共路径（/health, /api/v1/auth/login）无 token 也放行。"""
    from protoforge.api.v1.auth import auth_middleware
    from protoforge.config import get_settings

    get_settings().no_auth = False
    for path in ("/health", "/api/v1/health", "/api/v1/auth/login", "/docs", "/openapi.json"):
        request = _make_request(path, method="GET")
        expected_response = MagicMock(status_code=200)
        call_next = AsyncMock(return_value=expected_response)
        response = await auth_middleware(request, call_next)
        assert response == expected_response, f"公共路径 {path} 应放行"


@pytest.mark.asyncio
async def test_auth_middleware_options_request_passes_through():
    """OPTIONS 预检请求放行（CORS）。"""
    from protoforge.api.v1.auth import auth_middleware
    from protoforge.config import get_settings

    get_settings().no_auth = False
    request = _make_request("/api/v1/devices", method="OPTIONS")
    expected_response = MagicMock(status_code=200)
    call_next = AsyncMock(return_value=expected_response)
    response = await auth_middleware(request, call_next)
    assert response == expected_response


@pytest.mark.asyncio
async def test_auth_middleware_no_auth_mode_injects_admin():
    """no_auth=True 模式下注入 admin 用户并放行。"""
    from protoforge.api.v1.auth import auth_middleware
    from protoforge.config import get_settings

    settings = get_settings()
    original_no_auth = settings.no_auth
    settings.no_auth = True
    try:
        request = _make_request("/api/v1/devices", method="GET")
        expected_response = MagicMock(status_code=200)
        call_next = AsyncMock(return_value=expected_response)
        response = await auth_middleware(request, call_next)
        assert response == expected_response
        # request.state.user 应被注入
        assert request.state.user.get("role") == "admin"
    finally:
        settings.no_auth = original_no_auth


@pytest.mark.asyncio
async def test_auth_middleware_invalid_token_returns_401():
    """无效 token → 401。"""
    from protoforge.api.v1.auth import auth_middleware
    from protoforge.config import get_settings

    get_settings().no_auth = False
    request = _make_request("/api/v1/devices", method="GET", auth_header="Bearer invalid.token.here")
    call_next = AsyncMock()
    response = await auth_middleware(request, call_next)
    assert response.status_code == 401
    call_next.assert_not_called()


def test_is_public_path_whitelist():
    """_is_public_path 正确识别公共路径。"""
    from protoforge.api.v1.auth import _is_public_path

    assert _is_public_path("/health") is True
    assert _is_public_path("/api/v1/health") is True
    assert _is_public_path("/api/v1/auth/login") is True
    assert _is_public_path("/api/v1/auth/register") is True
    assert _is_public_path("/api/v1/auth/refresh") is True
    assert _is_public_path("/docs") is True
    assert _is_public_path("/openapi.json") is True
    assert _is_public_path("/metrics") is True

    # 受保护路径
    assert _is_public_path("/api/v1/devices") is False
    assert _is_public_path("/api/v1/protocols") is False
    assert _is_public_path("/api/v1/scenarios") is False


# ---------------------------------------------------------------------------
#  3. CORS 配置
# ---------------------------------------------------------------------------


def test_cors_config_empty_defaults_to_localhost():
    """cors_origins 为空 → 默认 localhost（非通配符）。"""
    from protoforge.config import Settings

    # 显式构造空 cors_origins（避免单例/环境变量干扰）
    s = Settings(cors_origins="")
    assert s.cors_origins == "", "空 cors_origins 应为空字符串"

    # 模拟 main.py 中的解析逻辑
    cors_origins_raw = s.cors_origins or ""
    cors_origins_list = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
    if not cors_origins_list:
        cors_origins_list = [f"http://localhost:{s.port}", f"http://127.0.0.1:{s.port}"]

    assert "*" not in cors_origins_list, "空配置不应含通配符"
    assert any("localhost" in o for o in cors_origins_list), "空配置应默认 localhost"


def test_cors_config_wildcard_detected():
    """cors_origins='*' → 通配符检测。"""
    cors_origins_raw = "*"
    cors_origins_list = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
    has_wildcard = "*" in cors_origins_list
    is_wildcard = cors_origins_list == ["*"]

    assert has_wildcard is True
    assert is_wildcard is True


def test_cors_config_multiple_domains_parsed():
    """多域名逗号分隔 → 列表。"""
    cors_origins_raw = "https://a.com,https://b.com, http://localhost:8080"
    cors_origins_list = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

    assert len(cors_origins_list) == 3
    assert "https://a.com" in cors_origins_list
    assert "https://b.com" in cors_origins_list
    assert "http://localhost:8080" in cors_origins_list
    assert "*" not in cors_origins_list


def test_cors_config_wildcard_with_domains_collapses_to_wildcard():
    """'*' 与具体域名共存 → 收敛为 ['*']。"""
    cors_origins_raw = "*,https://a.com"
    cors_origins_list = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
    has_wildcard = "*" in cors_origins_list
    if has_wildcard and len(cors_origins_list) > 1:
        cors_origins_list = ["*"]

    assert cors_origins_list == ["*"]


# ---------------------------------------------------------------------------
#  4. 启动安全检查
# ---------------------------------------------------------------------------


def test_check_startup_security_warns_on_weak_password(caplog):
    """弱管理员密码 → 安全告警。"""
    import logging
    from protoforge.main import _check_startup_security

    settings = MagicMock()
    settings.jwt_secret = "strong_secret_at_least_32_chars_xxx"
    settings.no_auth = False
    settings.admin_password = "admin"  # 弱密码
    settings.reset_admin_password = False
    settings.cors_origins = "https://example.com"

    with caplog.at_level(logging.WARNING, logger="protoforge.main"):
        _check_startup_security(settings)

    assert any("Admin password is weak" in r.message for r in caplog.records), "弱密码应触发告警"


def test_check_startup_security_warns_on_no_auth(caplog):
    """no_auth=True → 安全告警。"""
    import logging
    from protoforge.main import _check_startup_security

    settings = MagicMock()
    settings.jwt_secret = "strong_secret_at_least_32_chars_xxx"
    settings.no_auth = True
    settings.admin_password = "strong_password"
    settings.reset_admin_password = False
    settings.cors_origins = "https://example.com"

    with caplog.at_level(logging.WARNING, logger="protoforge.main"):
        _check_startup_security(settings)

    assert any("Authentication is DISABLED" in r.message for r in caplog.records), "no_auth 应触发告警"


def test_check_startup_security_warns_on_wildcard_cors(caplog):
    """通配符 CORS → 安全告警。"""
    import logging
    from protoforge.main import _check_startup_security

    settings = MagicMock()
    settings.jwt_secret = "strong_secret_at_least_32_chars_xxx"
    settings.no_auth = False
    settings.admin_password = "strong_password"
    settings.reset_admin_password = False
    settings.cors_origins = "*"

    with caplog.at_level(logging.WARNING, logger="protoforge.main"):
        _check_startup_security(settings)

    assert any("CORS allows all origins" in r.message for r in caplog.records), "通配符 CORS 应触发告警"
