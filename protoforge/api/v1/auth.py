import logging
import time
from typing import Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from protoforge.core.auth import verify_token, verify_token_with_reason

logger = logging.getLogger(__name__)


def is_no_auth() -> bool:
    from protoforge.config import get_settings
    return get_settings().no_auth


class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self._allowed_roles = allowed_roles

    async def __call__(self, request: Request) -> dict:
        if is_no_auth():
            return {"sub": "no-auth", "username": "admin", "role": "admin"}
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

_PUBLIC_PATHS = {
    "/api/v1/auth/login",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/health",
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


def _get_user_from_request(request: Request) -> Optional[dict]:
    return getattr(request.state, "user", None)


def _check_role(request: Request, allowed_roles: list[str]) -> Optional[JSONResponse]:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"code": 401, "data": None, "message": "Not authenticated", "detail": "Not authenticated", "reason": "no_token", "timestamp": int(time.time() * 1000)},
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_role = user.get("role", "user")
    if user_role not in allowed_roles:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"code": 403, "data": None, "message": f"角色 '{user_role}' 无权执行此操作", "detail": f"Role '{user_role}' not allowed for this operation", "timestamp": int(time.time() * 1000)},
        )
    return None


_ADMIN_PATHS = {
    "/api/v1/auth/admin/reset-password": ["admin"],
    "/api/v1/auth/admin/unlock": ["admin"],
}
_ADMIN_ROLE_PATH = "/api/v1/auth/users/"
_ADMIN_ROLE_SUFFIX = "/role"


async def auth_middleware(request: Request, call_next):
    path = request.url.path

    if request.method == "OPTIONS":
        return await call_next(request)

    if _is_public_path(path):
        return await call_next(request)

    if not path.startswith("/api/v1/"):
        return await call_next(request)

    if is_no_auth():
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
        detail = "Token已过期，请重新登录" if reason == "token_expired" else "无效的认证令牌"
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"code": 401, "data": None, "message": detail, "detail": detail, "reason": reason, "timestamp": int(time.time() * 1000)},
            headers={"WWW-Authenticate": "Bearer"},
        )

    request.state.user = payload

    for admin_path, roles in _ADMIN_PATHS.items():
        if path.startswith(admin_path):
            resp = _check_role(request, roles)
            if resp:
                return resp
            break

    if path.startswith(_ADMIN_ROLE_PATH) and path.endswith(_ADMIN_ROLE_SUFFIX):
        resp = _check_role(request, ["admin"])
        if resp:
            return resp

    return await call_next(request)
