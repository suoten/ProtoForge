import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from protoforge.api.v1.auth import require_admin, require_user, require_guest
from protoforge.core.messages import desc

router = APIRouter()
logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, description="Username")
    password: str = Field(..., min_length=1, description="Password")

    @field_validator("username", "password", mode="after")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1, description="Refresh token")


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, description="Username")
    password: str = Field(..., min_length=1, description="Password")

    @field_validator("username", "password", mode="after")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


class ChangePasswordRequest(BaseModel):
    username: str = Field(..., min_length=1, description="Username")
    old_password: str = Field(..., min_length=1, description="Current password")
    new_password: str = Field(..., min_length=1, description="New password")


class AdminResetPasswordRequest(BaseModel):
    username: str = Field(..., min_length=1, description="Username")
    new_password: str = Field(..., min_length=1, description="New password")


class UpdateRoleRequest(BaseModel):
    role: str = Field(..., min_length=1, description="New role")


@router.post("/auth/login")
async def login(credentials: LoginRequest):
    try:
        from protoforge.core.auth import user_manager, create_token, create_refresh_token
        user, error_code = await user_manager.authenticate(credentials.username, credentials.password)

        if not user:
            if isinstance(error_code, str) and error_code.startswith("account_locked:"):
                remaining = error_code.split(":")[1] if ":" in error_code else ""
                raise HTTPException(status_code=423, detail=f"Account locked, retry after {remaining}s")
            raise HTTPException(status_code=401, detail="Invalid username or password")
        access_token = create_token(
            user.id, user.username, user.role,
            token_version=user_manager.get_token_version(user.id),
        )
        refresh_token = create_refresh_token(user.id)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "username": user.username,
            "role": user.role,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Login failed: %s", e)
        raise HTTPException(status_code=500, detail="Login failed, please try again later") from e


@router.post("/auth/refresh")
async def refresh_token(data: RefreshRequest):
    try:
        from protoforge.core.auth import verify_refresh_token, create_token, create_refresh_token, user_manager
        user_id = verify_refresh_token(data.refresh_token)

        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

        user = user_manager.get_user_by_id(user_id)

        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        access_token = create_token(
            user.id, user.username, user.role,
            token_version=user_manager.get_token_version(user.id),
        )
        new_refresh_token = create_refresh_token(user.id)
        return {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
            "username": user.username,
            "role": user.role,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Token refresh failed: %s", e)
        raise HTTPException(status_code=500, detail="Token refresh failed") from e


@router.post("/auth/register")
async def register(user_data: RegisterRequest):
    from protoforge.core.auth import user_manager

    try:
        user = await user_manager.create_user(user_data.username, user_data.password, role="user")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error("User creation failed: %s", e)
        raise HTTPException(status_code=500, detail="User creation failed, please try again later") from e

    if not user:
        raise HTTPException(status_code=409, detail="Username already exists")

    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/auth/me")
async def get_current_user(_user: dict = Depends(require_guest)):
    from protoforge.core.auth import user_manager
    username = _user.get("username", "")
    user = user_manager.get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "created_at": user.created_at,
        "locked": bool(user.locked_until and user.locked_until > time.time()),
    }


@router.get("/auth/users")
async def list_users(_user: dict = Depends(require_admin)):
    try:
        from protoforge.core.auth import user_manager
        return {"users": user_manager.list_users()}
    except Exception as e:
        logger.error("Failed to list users: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list users") from e


@router.post("/auth/change-password")
async def change_password(data: ChangePasswordRequest, _user: dict = Depends(require_guest)):
    try:
        from protoforge.core.auth import user_manager

        current_user_id = _user.get("sub", "")
        current_user = user_manager.get_user_by_id(current_user_id) if current_user_id else None
        current_username = current_user.username if current_user else _user.get("username", "")

        is_admin = (current_user.role if current_user else _user.get("role")) == "admin"
        is_self = data.username == current_username

        if not is_admin and not is_self:
            raise HTTPException(status_code=403, detail=desc("auth.change_own_password_only"))

        if is_admin and not is_self:
            ok, msg = await user_manager.admin_reset_password(data.username, data.new_password)
        else:
            ok, msg = await user_manager.change_password(data.username, data.old_password, data.new_password)

        if not ok:
            raise HTTPException(status_code=400, detail=msg)

        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Change password failed: %s", e)
        raise HTTPException(status_code=500, detail=desc("auth.password_change_failed")) from e


@router.post("/auth/admin/reset-password")
async def admin_reset_password(data: AdminResetPasswordRequest, _user: dict = Depends(require_admin)):
    try:
        from protoforge.core.auth import user_manager

        ok, msg = await user_manager.admin_reset_password(data.username, data.new_password)

        if not ok:
            raise HTTPException(status_code=400, detail=msg)

        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Admin reset password failed: %s", e)
        raise HTTPException(status_code=500, detail="Password reset failed, please try again later") from e


@router.put("/auth/users/{username}/role")
async def update_user_role(username: str, data: UpdateRoleRequest, _user: dict = Depends(require_admin)):
    try:
        from protoforge.core.auth import user_manager
        valid_roles = {"admin", "operator", "user", "viewer", "guest"}
        if data.role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Invalid role: {data.role}. Valid roles: {', '.join(sorted(valid_roles))}")
        if not await user_manager.update_user_role(username, data.role):
            raise HTTPException(status_code=400, detail="Failed to update role. Cannot demote the last admin.")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Update user role failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to update user role") from e


@router.post("/auth/admin/unlock/{username}")
async def admin_unlock_user(username: str, _user: dict = Depends(require_admin)):
    try:
        from protoforge.core.auth import user_manager
        if not await user_manager.reset_login_attempts(username):
            raise HTTPException(status_code=404, detail="User not found")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unlock user failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to unlock user") from e


@router.delete("/auth/users/{username}")
async def delete_user(username: str, _user: dict = Depends(require_admin)):
    try:
        from protoforge.core.auth import user_manager
        if not await user_manager.delete_user(username):
            raise HTTPException(status_code=400, detail="Cannot delete this user. Admin account or last admin cannot be deleted.")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Delete user failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to delete user") from e
