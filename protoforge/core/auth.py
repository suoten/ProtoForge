import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import jwt
from passlib.context import CryptContext

logger = logging.getLogger(__name__)

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_SECRET_KEY: str = ""


def _generate_secret_key() -> str:
    return secrets.token_urlsafe(32)


def set_secret_key(key: str) -> None:
    global _SECRET_KEY
    if not key or key == "protoforge-secret-change-me":
        _SECRET_KEY = _generate_secret_key()
        logger.warning(
            "JWT secret was using default/weak value. A new secure key has been generated. "
            "Set PROTOFORGE_JWT_SECRET in your .env to avoid token invalidation on restart."
        )
    else:
        _SECRET_KEY = key


def get_secret_key() -> str:
    global _SECRET_KEY
    if not _SECRET_KEY:
        _SECRET_KEY = _generate_secret_key()
        logger.warning(
            "JWT secret not configured. Using auto-generated key. "
            "Set PROTOFORGE_JWT_SECRET in your .env to avoid token invalidation on restart."
        )
    return _SECRET_KEY


def create_token(user_id: str, username: str, role: str = "user", expires_in: int = 1800) -> str:
    now = time.time()
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": int(now),
        "exp": int(now + expires_in),
        "jti": uuid.uuid4().hex,
        "type": "access",
    }
    return jwt.encode(payload, get_secret_key(), algorithm="HS256")


def create_refresh_token(user_id: str, expires_in: int = 604800) -> str:
    now = time.time()
    payload = {
        "sub": user_id,
        "iat": int(now),
        "exp": int(now + expires_in),
        "jti": uuid.uuid4().hex,
        "type": "refresh",
    }
    return jwt.encode(payload, get_secret_key(), algorithm="HS256")


def verify_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug("Invalid token: %s", e)
        return None


def verify_refresh_token(token: str) -> Optional[str]:
    payload = verify_token(token)
    if not payload:
        return None
    if payload.get("type") != "refresh":
        return None
    return payload.get("sub")


@dataclass
class User:
    id: str
    username: str
    password_hash: str
    role: str = "user"
    created_at: float = field(default_factory=time.time)
    login_attempts: int = 0
    locked_until: float = 0.0

    def to_dict(self, include_hash: bool = False) -> dict:
        d = {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "created_at": self.created_at,
            "login_attempts": self.login_attempts,
            "locked_until": self.locked_until,
        }
        if include_hash:
            d["password_hash"] = self.password_hash
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        return cls(
            id=data["id"],
            username=data["username"],
            password_hash=data["password_hash"],
            role=data.get("role", "user"),
            created_at=data.get("created_at", time.time()),
            login_attempts=data.get("login_attempts", 0),
            locked_until=data.get("locked_until", 0.0),
        )


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password, password_hash)
    except Exception:
        return False


def _is_password_strong(password: str) -> tuple[bool, str]:
    if len(password) < 8:
        return False, "密码长度至少8位"
    if not any(c.isupper() for c in password):
        return False, "密码必须包含大写字母"
    if not any(c.islower() for c in password):
        return False, "密码必须包含小写字母"
    if not any(c.isdigit() for c in password):
        return False, "密码必须包含数字"
    return True, ""


_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_DURATION = 300


class UserManager:
    def __init__(self):
        self._users: dict[str, User] = {}
        self._db = None
        default_password = os.environ.get("PROTOFORGE_ADMIN_PASSWORD", "admin")
        admin_hash = hash_password(default_password)
        self._users["admin"] = User(
            id="admin", username="admin", password_hash=admin_hash, role="admin",
        )

    def set_database(self, db) -> None:
        self._db = db

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        for u in self._users.values():
            if u.id == user_id:
                return u
        return None

    async def restore_from_db(self) -> None:
        if not self._db:
            return
        try:
            users = await self._db.load_all_users()
            for u in users:
                user = User.from_dict(u)
                if user.username != "admin":
                    self._users[user.username] = user
            logger.info("Restored %d users from database", len(users))
        except Exception as e:
            logger.warning("Failed to restore users: %s", e)

    def authenticate(self, username: str, password: str) -> tuple[Optional[User], str]:
        user = self._users.get(username)
        if not user:
            return None, "invalid_credentials"

        if user.locked_until > time.time():
            remaining = int(user.locked_until - time.time())
            logger.warning("User %s is locked until %.0f", username, user.locked_until)
            return None, f"account_locked:{remaining}"

        if not verify_password(password, user.password_hash):
            user.login_attempts += 1
            if user.login_attempts >= _MAX_LOGIN_ATTEMPTS:
                user.locked_until = time.time() + _LOCKOUT_DURATION
                logger.warning("User %s locked for %d seconds due to failed logins", username, _LOCKOUT_DURATION)
            self._persist_user(user)
            return None, "invalid_credentials"

        user.login_attempts = 0
        user.locked_until = 0.0
        self._persist_user(user)
        return user, ""

    def _persist_user(self, user: User) -> None:
        if not self._db:
            return
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._db.save_user(user.to_dict(include_hash=True)))

            def _on_persist_done(t):
                try:
                    t.result()
                except Exception as exc:
                    logger.warning("Failed to persist user %s: %s", user.username, exc)

            task.add_done_callback(_on_persist_done)
        except RuntimeError:
            logger.debug("No event loop, skipping user persist for %s", user.username)
        except Exception as e:
            logger.warning("Failed to persist user %s: %s", user.username, e)

    async def create_user(self, username: str, password: str, role: str = "user") -> Optional[User]:
        if username in self._users:
            return None
        ok, msg = _is_password_strong(password)
        if not ok:
            logger.warning("Password too weak for user %s: %s", username, msg)
            return None
        user = User(
            id=uuid.uuid4().hex[:12],
            username=username,
            password_hash=hash_password(password),
            role=role,
        )
        self._users[username] = user
        if self._db:
            try:
                await self._db.save_user(user.to_dict(include_hash=True))
            except Exception as e:
                logger.warning("Failed to persist user: %s", e)
        return user

    async def delete_user(self, username: str) -> bool:
        if username == "admin":
            return False
        if username in self._users:
            del self._users[username]
            if self._db:
                try:
                    await self._db.delete_user(username)
                except Exception as e:
                    logger.warning("Failed to delete user from DB: %s", e)
            return True
        return False

    def list_users(self) -> list[dict]:
        return [
            {"id": u.id, "username": u.username, "role": u.role, "created_at": u.created_at}
            for u in self._users.values()
        ]

    async def change_password(self, username: str, old_password: str, new_password: str) -> tuple[bool, str]:
        user = self._users.get(username)
        if not user or not verify_password(old_password, user.password_hash):
            return False, "原密码错误"
        ok, msg = _is_password_strong(new_password)
        if not ok:
            return False, msg
        user.password_hash = hash_password(new_password)
        if self._db:
            try:
                await self._db.save_user(user.to_dict(include_hash=True))
            except Exception as e:
                logger.warning("Failed to update user password: %s", e)
        return True, ""

    async def reset_login_attempts(self, username: str) -> bool:
        user = self._users.get(username)
        if not user:
            return False
        user.login_attempts = 0
        user.locked_until = 0.0
        if self._db:
            try:
                await self._db.save_user(user.to_dict(include_hash=True))
            except Exception as e:
                logger.warning("Failed to reset login attempts: %s", e)
        return True

    async def admin_reset_password(self, username: str, new_password: str) -> tuple[bool, str]:
        user = self._users.get(username)
        if not user:
            return False, "用户不存在"
        ok, msg = _is_password_strong(new_password)
        if not ok:
            return False, msg
        user.password_hash = hash_password(new_password)
        user.login_attempts = 0
        user.locked_until = 0.0
        if self._db:
            try:
                await self._db.save_user(user.to_dict(include_hash=True))
            except Exception as e:
                logger.warning("Failed to reset user password: %s", e)
        return True, ""

    async def update_user_role(self, username: str, new_role: str) -> bool:
        user = self._users.get(username)
        if not user:
            return False
        if new_role not in ("admin", "operator", "viewer", "user"):
            return False
        user.role = new_role
        if self._db:
            try:
                await self._db.save_user(user.to_dict(include_hash=True))
            except Exception as e:
                logger.warning("Failed to update user role: %s", e)
        return True


user_manager = UserManager()
