import logging
import os
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from protoforge.core.auth import verify_token

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

_NO_AUTH = os.environ.get("PROTOFORGE_NO_AUTH", "").lower() in ("1", "true", "yes")


class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self._allowed_roles = allowed_roles

    async def __call__(
        self,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    ) -> dict:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        payload = verify_token(credentials.credentials)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
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
    "/metrics",
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


def _check_role(request: Request, allowed_roles: list[str]) -> None:
    user = _get_user_from_request(request)
    if not user:
        return
    user_role = user.get("role", "user")
    if user_role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user_role}' not allowed for this operation",
        )


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

    if _NO_AUTH:
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Not authenticated"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:]
    payload = verify_token(token)
    if payload is None:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid or expired token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    request.state.user = payload

    for admin_path, roles in _ADMIN_PATHS.items():
        if path.startswith(admin_path):
            _check_role(request, roles)
            break

    if path.startswith(_ADMIN_ROLE_PATH) and path.endswith(_ADMIN_ROLE_SUFFIX):
        _check_role(request, ["admin"])

    return await call_next(request)
