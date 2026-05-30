import logging
import time

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from protoforge.core.auth import verify_token_with_reason

logger = logging.getLogger(__name__)


_no_auth_warning_shown = False

def is_no_auth() -> bool:
    global _no_auth_warning_shown
    from protoforge.config import get_settings
    settings = get_settings()
    if settings.no_auth:
        host = getattr(settings, 'host', '0.0.0.0')
        if host not in ('127.0.0.1', 'localhost', '::1') and not _no_auth_warning_shown:
            logger.critical(
                "SECURITY: PROTOFORGE_NO_AUTH is enabled but server is bound to %s (non-localhost). "
                "Anyone on the network can access all APIs without authentication! "
                "Set PROTOFORGE_NO_AUTH=false or bind to 127.0.0.1 for development.",
                host
            )
            _no_auth_warning_shown = True
    return settings.no_auth


class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self._allowed_roles = allowed_roles

    async def __call__(self, request: Request) -> dict:
        if is_no_auth():
            return {"sub": "no-auth", "username": "anonymous", "role": "viewer"}
        payload = getattr(request.state, "user", None)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_role = payload.get("role", "user")
        if user_role not in self._allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user_role}' not allowed. Required: {self._allowed_roles}",
            )
        return payload


require_admin = RoleChecker(["admin"])
require_operator = RoleChecker(["admin", "operator"])
require_user = RoleChecker(["admin", "operator", "user"])
require_viewer = RoleChecker(["admin", "operator", "user", "viewer"])
require_guest = RoleChecker(["admin", "operator", "user", "viewer", "guest"])  # FIXED-P1: 添加guest角色

_PUBLIC_PATHS = {
    "/api/v1/auth/login",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/health",
    "/api/v1/health",
    "/metrics",
    "/api/v1/metrics",
}

_PUBLIC_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
)


def _is_public_path(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    for prefix in _PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


async def auth_middleware(request: Request, call_next):
    path = request.url.path

    if request.method == "OPTIONS":
        return await call_next(request)

    if _is_public_path(path):
        return await call_next(request)

    if not path.startswith("/api/v1/"):
        return await call_next(request)

    if is_no_auth():
        request.state.user = {"username": "admin", "role": "admin"}
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"code": 401, "data": None, "message": "Not authenticated", "detail": "Not authenticated", "reason": "no_token", "timestamp": int(time.time() * 1000)},
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:]
    payload, reason = verify_token_with_reason(token)
    if payload is None:
        detail = "Token expired, please log in again" if reason == "token_expired" else "Invalid authentication token"
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"code": 401, "data": None, "message": detail, "detail": detail, "reason": reason, "timestamp": int(time.time() * 1000)},
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_ver = payload.get("ver", 0)
    user_id = payload.get("sub", "")
    if user_id:
        from protoforge.core.auth import user_manager
        current_ver = user_manager.get_token_version(user_id)
        if current_ver != token_ver:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"code": 401, "data": None, "message": "Token invalidated due to role change, please re-login", "detail": "Token invalidated due to role change, please re-login", "reason": "token_version_mismatch", "timestamp": int(time.time() * 1000)},
                headers={"WWW-Authenticate": "Bearer"},
            )

    request.state.user = payload

    return await call_next(request)
