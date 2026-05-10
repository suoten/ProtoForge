import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from protoforge.api.v1.auth import require_admin, require_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/auth/login")
async def login(credentials: dict[str, Any]):
    try:
        from protoforge.core.auth import user_manager, create_token, create_refresh_token
        username = credentials.get("username", "")
        password = credentials.get("password", "")
        if not isinstance(username, str) or not isinstance(password, str):
            raise HTTPException(status_code=400, detail="用户名和密码必须为字符串")
        username = username.strip()
        password = password.strip()
        if not username or not password:
            raise HTTPException(status_code=400, detail="用户名和密码不能为空")
        user, error_code = await user_manager.authenticate(username, password)

        if not user:
            if isinstance(error_code, str) and error_code.startswith("account_locked:"):
                remaining = error_code.split(":")[1] if ":" in error_code else ""
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Login failed: %s", e)
        raise HTTPException(status_code=500, detail="登录失败，请稍后重试") from e


@router.post("/auth/refresh")
async def refresh_token(data: dict[str, Any]):
    try:
        from protoforge.core.auth import verify_refresh_token, create_token, create_refresh_token, user_manager
        refresh = data.get("refresh_token", "")
        if not isinstance(refresh, str) or not refresh.strip():
            raise HTTPException(status_code=401, detail="refresh_token 无效或已过期")
        user_id = verify_refresh_token(refresh)

        if not user_id:
            raise HTTPException(status_code=401, detail="refresh_token 无效或已过期")

        user = user_manager.get_user_by_id(user_id)

        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")

        access_token = create_token(user.id, user.username, user.role)
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
        raise HTTPException(status_code=500, detail="令牌刷新失败") from e


@router.post("/auth/register")
async def register(user_data: dict[str, Any]):
    from protoforge.core.auth import user_manager
    username = user_data.get("username", "")
    password = user_data.get("password", "")

    if not isinstance(username, str) or not isinstance(password, str):
        raise HTTPException(status_code=400, detail="用户名和密码必须为字符串")
    username = username.strip()
    password = password.strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    try:
        user = await user_manager.create_user(username, password, role="user")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error("User creation failed: %s", e)
        raise HTTPException(status_code=500, detail="用户创建失败，请稍后重试") from e

    if not user:
        raise HTTPException(status_code=409, detail="用户名已存在")

    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/auth/users")
async def list_users(_user: dict = Depends(require_admin)):
    try:
        from protoforge.core.auth import user_manager
        return {"users": user_manager.list_users()}
    except Exception as e:
        logger.error("Failed to list users: %s", e)
        raise HTTPException(status_code=500, detail="获取用户列表失败") from e


@router.post("/auth/change-password")
async def change_password(data: dict[str, Any], _user: dict = Depends(require_user)):
    try:
        from protoforge.core.auth import user_manager
        username = data.get("username", "")
        old_password = data.get("old_password", "")
        new_password = data.get("new_password", "")

        if _user.get("role") != "admin" and username != _user.get("username", ""):
            raise HTTPException(status_code=403, detail="只能修改自己的密码")

        ok, msg = await user_manager.change_password(username, old_password, new_password)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)

        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Change password failed: %s", e)
        raise HTTPException(status_code=500, detail="修改密码失败，请稍后重试") from e


@router.post("/auth/admin/reset-password")
async def admin_reset_password(data: dict[str, Any], _user: dict = Depends(require_admin)):
    try:
        from protoforge.core.auth import user_manager

        username = data.get("username", "")
        new_password = data.get("new_password", "")

        if not username or not new_password:
            raise HTTPException(status_code=400, detail="用户名和新密码不能为空")

        ok, msg = await user_manager.admin_reset_password(username, new_password)

        if not ok:
            raise HTTPException(status_code=400, detail=msg)

        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Admin reset password failed: %s", e)
        raise HTTPException(status_code=500, detail="重置密码失败，请稍后重试") from e


@router.put("/auth/users/{username}/role")
async def update_user_role(username: str, data: dict[str, Any], _user: dict = Depends(require_admin)):
    try:
        from protoforge.core.auth import user_manager
        new_role = data.get("role", "")
        if not new_role:
            raise HTTPException(status_code=400, detail="角色不能为空")
        valid_roles = {"admin", "operator", "user", "viewer"}
        if new_role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"无效的角色: {new_role}，有效值为: {', '.join(valid_roles)}")
        if not await user_manager.update_user_role(username, new_role):
            raise HTTPException(status_code=400, detail="更新角色失败")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Update user role failed: %s", e)
        raise HTTPException(status_code=500, detail="更新角色失败") from e


@router.post("/auth/admin/unlock/{username}")
async def admin_unlock_user(username: str, _user: dict = Depends(require_admin)):
    try:
        from protoforge.core.auth import user_manager
        if not await user_manager.reset_login_attempts(username):
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unlock user failed: %s", e)
        raise HTTPException(status_code=500, detail="解锁用户失败") from e


@router.delete("/auth/users/{username}")
async def delete_user(username: str, _user: dict = Depends(require_admin)):
    try:
        from protoforge.core.auth import user_manager
        if not await user_manager.delete_user(username):
            raise HTTPException(status_code=400, detail="无法删除该用户")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Delete user failed: %s", e)
        raise HTTPException(status_code=500, detail="删除用户失败") from e
