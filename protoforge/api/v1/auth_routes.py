import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from protoforge.api.v1.auth import require_admin, require_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/auth/login")
async def login(credentials: dict[str, Any]):
    from protoforge.core.auth import user_manager, create_token, create_refresh_token
    username = credentials.get("username", "")
    password = credentials.get("password", "")
    user, error_code = await user_manager.authenticate(username, password)

    if not user:
        if error_code.startswith("account_locked:"):
            remaining = error_code.split(":")[1]
            raise HTTPException(status_code=423, detail=f"账户已锁定，请{remaining}秒后重试")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    access_token = create_token(user.id, user.username, user.role)
    refresh_token = create_refresh_token(user.id)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role,
    }


@router.post("/auth/refresh")
async def refresh_token(data: dict[str, Any]):
    from protoforge.core.auth import verify_refresh_token, create_token, create_refresh_token, user_manager
    refresh = data.get("refresh_token", "")
    user_id = verify_refresh_token(refresh)

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = user_manager.get_user_by_id(user_id)

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    access_token = create_token(user.id, user.username, user.role)
    new_refresh_token = create_refresh_token(user.id)
    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role,
    }


@router.post("/auth/register")
async def register(user_data: dict[str, Any]):
    from protoforge.core.auth import user_manager
    username = user_data.get("username", "")
    password = user_data.get("password", "")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    try:
        user = await user_manager.create_user(username, password, role="user")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not user:
        raise HTTPException(status_code=409, detail="Username already exists")

    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/auth/users")
async def list_users(_user: dict = Depends(require_admin)):
    from protoforge.core.auth import user_manager
    return user_manager.list_users()


@router.post("/auth/change-password")
async def change_password(data: dict[str, Any], _user: dict = Depends(require_user)):
    from protoforge.core.auth import user_manager
    username = data.get("username", "")
    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")

    if _user.get("role") != "admin" and username != _user.get("username", ""):
        raise HTTPException(status_code=403, detail="Can only change your own password")

    ok, msg = await user_manager.change_password(username, old_password, new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    return {"status": "ok"}


@router.post("/auth/admin/reset-password")
async def admin_reset_password(data: dict[str, Any], _user: dict = Depends(require_admin)):
    from protoforge.core.auth import user_manager

    username = data.get("username", "")
    new_password = data.get("new_password", "")

    if not username or not new_password:
        raise HTTPException(status_code=400, detail="username and new_password required")

    ok, msg = await user_manager.admin_reset_password(username, new_password)

    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    return {"status": "ok"}


@router.put("/auth/users/{username}/role")
async def update_user_role(username: str, data: dict[str, Any], _user: dict = Depends(require_admin)):
    from protoforge.core.auth import user_manager
    new_role = data.get("role", "")
    if not new_role:
        raise HTTPException(status_code=400, detail="role is required")
    if not await user_manager.update_user_role(username, new_role):
        raise HTTPException(status_code=400, detail="Failed to update role")
    return {"status": "ok"}


@router.post("/auth/admin/unlock/{username}")
async def admin_unlock_user(username: str, _user: dict = Depends(require_admin)):
    from protoforge.core.auth import user_manager
    if not await user_manager.reset_login_attempts(username):
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "ok"}


@router.delete("/auth/users/{username}")
async def delete_user(username: str, _user: dict = Depends(require_admin)):
    from protoforge.core.auth import user_manager
    if not await user_manager.delete_user(username):
        raise HTTPException(status_code=400, detail="Cannot delete this user")
    return {"status": "ok"}
