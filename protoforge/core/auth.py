import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import jwt

logger = logging.getLogger(__name__)

_SECRET_KEY = "protoforge-default-secret-change-in-production"


def set_secret_key(key: str) -> None:
    global _SECRET_KEY
    _SECRET_KEY = key


def create_token(user_id: str, username: str, role: str = "user", expires_in: int = 86400) -> str:
    now = time.time()
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": int(now),
        "exp": int(now + expires_in),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _SECRET_KEY, algorithm="HS256")


def verify_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug("Invalid token: %s", e)
        return None


@dataclass
class User:
    id: str
    username: str
    password_hash: str
    role: str = "user"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "username": self.username,
            "password_hash": self.password_hash, "role": self.role,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        return cls(
            id=data["id"], username=data["username"],
            password_hash=data["password_hash"], role=data.get("role", "user"),
            created_at=data.get("created_at", time.time()),
        )


def hash_password(password: str) -> str:
    salt = "protoforge"
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


class UserManager:
    def __init__(self):
        self._users: dict[str, User] = {}
        self._db = None
        admin_hash = hash_password("admin")
        self._users["admin"] = User(
            id="admin", username="admin", password_hash=admin_hash, role="admin",
        )

    def set_database(self, db) -> None:
        self._db = db

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

    def authenticate(self, username: str, password: str) -> Optional[User]:
        user = self._users.get(username)
        if not user:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    async def create_user(self, username: str, password: str, role: str = "user") -> Optional[User]:
        if username in self._users:
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
                await self._db.save_user(user.to_dict())
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

    async def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        user = self._users.get(username)
        if not user or not verify_password(old_password, user.password_hash):
            return False
        user.password_hash = hash_password(new_password)
        if self._db:
            try:
                await self._db.save_user(user.to_dict())
            except Exception as e:
                logger.warning("Failed to update user password: %s", e)
        return True


user_manager = UserManager()
