import logging
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import jwt
from passlib.context import CryptContext

logger = logging.getLogger(__name__)

_USERNAME_MAX_LENGTH = 63  # FIXED: named constant for username regex max length
_SECRET_KEY_MIN_LENGTH = 32  # FIXED: named constant for minimum JWT secret key length
_ACCESS_TOKEN_EXPIRE_SECONDS = 1800  # FIXED: named constant (30 min)
_REFRESH_TOKEN_EXPIRE_SECONDS = 604800  # FIXED: named constant (7 days)

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_VALID_USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,' + str(_USERNAME_MAX_LENGTH) + r'}$')  # FIXED: use named constant

_SECRET_KEY: str = ""
_SECRET_KEY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", ".jwt_secret")


def _generate_secret_key() -> str:
    return secrets.token_urlsafe(_SECRET_KEY_MIN_LENGTH)  # FIXED: use named constant


def _load_persistent_secret_key() -> str:
    global _SECRET_KEY
    try:
        key_dir = os.path.dirname(_SECRET_KEY_FILE)
        os.makedirs(key_dir, exist_ok=True)
        if os.path.exists(_SECRET_KEY_FILE):
            with open(_SECRET_KEY_FILE, "r") as f:
                saved = f.read().strip()
            if saved and len(saved) >= _SECRET_KEY_MIN_LENGTH:  # FIXED: use named constant
                _SECRET_KEY = saved
                return saved
    except Exception as e:
        logger.debug("Could not load persistent JWT secret: %s", e)
    new_key = _generate_secret_key()
    _SECRET_KEY = new_key
    try:
        key_dir = os.path.dirname(_SECRET_KEY_FILE)
        os.makedirs(key_dir, exist_ok=True)
        with open(_SECRET_KEY_FILE, "w") as f:
            f.write(new_key)
        logger.info("Generated and saved new JWT secret to %s", _SECRET_KEY_FILE)
    except Exception as e:
        logger.warning("Could not persist JWT secret: %s. Tokens will invalidate on restart.", e)
    return new_key


def set_secret_key(key: str) -> None:
    global _SECRET_KEY
    if not key or key.strip() == key[:8] and len(key) < 24:
        _load_persistent_secret_key()
        if not _SECRET_KEY:
            logger.warning(
                "JWT secret not configured. Using auto-generated key. "
                "Set PROTOFORGE_JWT_SECRET in your .env for explicit control."
            )
    else:
        _SECRET_KEY = key


def get_secret_key() -> str:
    global _SECRET_KEY
    if not _SECRET_KEY:
        _load_persistent_secret_key()
    return _SECRET_KEY


def create_token(user_id: str, username: str, role: str = "user", expires_in: int = None) -> str:
    if expires_in is None:
        from protoforge.config import get_settings
        expires_in = get_settings().access_token_expires
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


def create_refresh_token(user_id: str, expires_in: int = None) -> str:
    if expires_in is None:
        from protoforge.config import get_settings
        expires_in = get_settings().refresh_token_expires
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


def verify_token_with_reason(token: str) -> tuple[Optional[dict], Optional[str]]:
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=["HS256"])
        return payload, None
    except jwt.ExpiredSignatureError:
        return None, "token_expired"
    except jwt.InvalidTokenError as e:
        return None, f"token_invalid:{e}"


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
    except Exception as e:
        logger.debug("Password verification failed: %s", e)
        return False


def _is_password_strong(password: str) -> tuple[bool, str]:
    from protoforge.config import get_settings
    min_length = get_settings().min_password_length
    if len(password) < min_length:
        return False, f"Password must be at least {min_length} characters"  # FIXED: hardcoded Chinese
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(not c.isalnum() for c in password)
    categories = sum([has_upper, has_lower, has_digit, has_special])
    if categories < 3:
        missing = []
        if not has_upper:
            missing.append("uppercase letter")
        if not has_lower:
            missing.append("lowercase letter")
        if not has_digit:
            missing.append("digit")
        if not has_special:
            missing.append("special character")
        return False, f"Password must contain at least 3 of: uppercase, lowercase, digit, special character. Missing: {', '.join(missing)}"  # FIXED: hardcoded Chinese
    return True, ""


_MAX_LOGIN_ATTEMPTS = None
_LOCKOUT_DURATION = None


def _get_max_login_attempts() -> int:
    global _MAX_LOGIN_ATTEMPTS
    if _MAX_LOGIN_ATTEMPTS is None:
        from protoforge.config import get_settings
        _MAX_LOGIN_ATTEMPTS = get_settings().max_login_attempts
    return _MAX_LOGIN_ATTEMPTS


def _get_lockout_duration() -> int:
    global _LOCKOUT_DURATION
    if _LOCKOUT_DURATION is None:
        from protoforge.config import get_settings
        _LOCKOUT_DURATION = get_settings().lockout_duration
    return _LOCKOUT_DURATION


class UserManager:
    def __init__(self):
        self._users: dict[str, User] = {}
        self._users_by_id: dict[str, User] = {}
        self._db = None
        try:
            from protoforge.config import get_settings
            default_password = get_settings().admin_password
            if not default_password:
                default_password = None
        except Exception as e:
            logger.warning("Failed to load admin password from config: %s", e)
            default_password = None
        if not default_password:
            default_password = secrets.token_urlsafe(16)
            logger.warning(
                "SECURITY: No admin password configured. A random password has been generated. "
                "Set the PROTOFORGE_ADMIN_PASSWORD environment variable for explicit control. "
                "Generated admin password (save this now, it will not be shown again): %s",
                default_password,
            )
        elif default_password == "admin":
            logger.warning(
                "SECURITY: Using default admin password 'admin'. "
                "Set PROTOFORGE_ADMIN_PASSWORD environment variable to change it in production!"
            )  # FIXED: warn when using default password
        admin_hash = hash_password(default_password)
        admin_user = User(
            id="admin", username="admin", password_hash=admin_hash, role="admin",
        )
        self._users["admin"] = admin_user
        self._users_by_id["admin"] = admin_user

    def set_database(self, db) -> None:
        self._db = db

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        return self._users_by_id.get(user_id)

    def get_user_by_username(self, username: str) -> Optional[User]:
        return self._users.get(username)

    async def restore_from_db(self) -> None:
        if not self._db:
            return
        try:
            users = await self._db.load_all_users()
            for u in users:
                user = User.from_dict(u)
                if user.username != "admin":
                    self._users[user.username] = user
                    self._users_by_id[user.id] = user
            logger.info("Restored %d users from database", len(users))
        except Exception as e:
            logger.warning("Failed to restore users: %s", e)

    async def authenticate(self, username: str, password: str) -> tuple[Optional[User], str]:
        user = self._users.get(username)
        if not user:
            return None, "invalid_credentials"

        if user.locked_until > time.time():
            remaining = int(user.locked_until - time.time())
            logger.warning("User %s is locked until %.0f", username, user.locked_until)
            return None, f"account_locked:{remaining}"

        if not verify_password(password, user.password_hash):
            user.login_attempts += 1
            max_attempts = _get_max_login_attempts()
            lockout_dur = _get_lockout_duration()
            if user.login_attempts >= max_attempts:
                user.locked_until = time.time() + lockout_dur
                logger.warning("User %s locked for %d seconds due to failed logins", username, lockout_dur)
            await self._persist_user(user)
            return None, "invalid_credentials"

        user.login_attempts = 0
        user.locked_until = 0.0
        await self._persist_user(user)
        return user, ""

    async def _persist_user(self, user: User) -> None:
        if not self._db:
            return
        try:
            await self._db.save_user(user.to_dict(include_hash=True))
        except Exception as e:
            logger.error("Failed to persist user %s: %s", user.username, e)
            raise RuntimeError(f"Failed to persist user: {e}") from e

    async def create_user(self, username: str, password: str, role: str = "user") -> Optional[User]:
        if not username or not isinstance(username, str):
            raise ValueError("Username must be a non-empty string")
        if not _VALID_USERNAME_PATTERN.match(username):
            raise ValueError(
                f"Username '{username}' is invalid. "
                "Must start with alphanumeric, contain only letters, digits, '_', '.', '-', max 64 chars"
            )
        if username.lower() in ("root", "system", "administrator", "null", "undefined"):
            raise ValueError(f"Username '{username}' is reserved and cannot be used")
        if username in self._users:
            return None
        ok, msg = _is_password_strong(password)
        if not ok:
            logger.warning("Password too weak for user %s: %s", username, msg)
            raise ValueError(msg)
        user = User(
            id=uuid.uuid4().hex[:12],
            username=username,
            password_hash=hash_password(password),
            role=role,
        )
        if self._db:
            try:
                await self._db.save_user(user.to_dict(include_hash=True))
            except Exception as e:
                logger.error("Failed to persist user %s: %s", username, e)
                raise RuntimeError(f"Failed to create user: {e}") from e
        self._users[username] = user
        self._users_by_id[user.id] = user
        return user

    async def delete_user(self, username: str) -> bool:
        if username == "admin":
            return False
        if username in self._users:
            user = self._users[username]
            if self._db:
                try:
                    await self._db.delete_user(username)
                except Exception as e:
                    logger.error("Failed to delete user %s from DB: %s", username, e)
                    raise RuntimeError(f"Failed to delete user: {e}") from e
            del self._users[username]
            self._users_by_id.pop(user.id, None)
            return True
        return False

    def list_users(self) -> list[dict]:
        return [
            {
                "id": u.id,
                "username": u.username,
                "role": u.role,
                "created_at": u.created_at,
                "locked": bool(u.locked_until and u.locked_until > time.time()),
            }
            for u in self._users.values()
        ]

    async def change_password(self, username: str, old_password: str, new_password: str) -> tuple[bool, str]:
        user = self._users.get(username)
        if not user or not verify_password(old_password, user.password_hash):
            return False, "Incorrect current password"  # FIXED: hardcoded Chinese
        ok, msg = _is_password_strong(new_password)
        if not ok:
            return False, msg
        old_hash = user.password_hash
        user.password_hash = hash_password(new_password)
        if self._db:
            try:
                await self._db.save_user(user.to_dict(include_hash=True))
            except Exception as e:
                logger.error("Failed to update user password for %s: %s", username, e)
                user.password_hash = old_hash
                return False, "Password update failed, please try again later"  # FIXED: hardcoded Chinese
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
            return False, "User not found"  # FIXED: hardcoded Chinese
        ok, msg = _is_password_strong(new_password)
        if not ok:
            return False, msg
        old_hash = user.password_hash
        old_attempts = user.login_attempts
        old_locked = user.locked_until
        user.password_hash = hash_password(new_password)
        user.login_attempts = 0
        user.locked_until = 0.0
        if self._db:
            try:
                await self._db.save_user(user.to_dict(include_hash=True))
            except Exception as e:
                logger.error("Failed to reset user password for %s: %s", username, e)
                user.password_hash = old_hash
                user.login_attempts = old_attempts
                user.locked_until = old_locked
                return False, "Password reset failed, please try again later"  # FIXED: hardcoded Chinese
        return True, ""

    async def update_user_role(self, username: str, new_role: str) -> bool:
        user = self._users.get(username)
        if not user:
            return False
        if new_role not in ("admin", "operator", "viewer", "user"):
            return False
        old_role = user.role
        user.role = new_role
        if self._db:
            try:
                await self._db.save_user(user.to_dict(include_hash=True))
            except Exception as e:
                logger.error("Failed to update user role for %s: %s", username, e)
                user.role = old_role
                return False
        return True


user_manager = UserManager()
