import logging
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class IntegrationAuth:
    def __init__(
        self,
        base_url: str,
        username: str = "admin",
        password: str = "",
        refresh_margin: float = 30.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._refresh_margin = refresh_margin
        self._token: str = ""
        self._refresh_token: str = ""
        self._token_expires: float = 0.0
        self._client = httpx.AsyncClient(timeout=10.0)

    @property
    def token(self) -> str:
        return self._token

    @property
    def is_authenticated(self) -> bool:
        return bool(self._token) and time.time() < self._token_expires - self._refresh_margin

    async def ensure_token(self) -> str:
        if self.is_authenticated:
            return self._token
        if self._refresh_token:
            try:
                await self._refresh_access_token()
                return self._token
            except Exception:
                pass
        await self._login()
        return self._token

    async def _login(self) -> None:
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/api/v1/auth/login",
                json={"username": self._username, "password": self._password},
            ) as resp:
                if resp.status_code != 200:
                    from protoforge.core.integration.retry import AuthError
                    raise AuthError(f"Login failed: HTTP {resp.status_code}")
                data = await resp.json()
        except httpx.ConnectError as e:
            from protoforge.core.integration.retry import NetworkError
            raise NetworkError(f"Connection failed: {e}") from e
        except httpx.TimeoutException as e:
            from protoforge.core.integration.retry import NetworkError
            raise NetworkError(f"Login timeout: {e}") from e
        self._token = data.get("access_token", "")
        self._refresh_token = data.get("refresh_token", "")
        expires_in = data.get("expires_in", 3600)
        self._token_expires = time.time() + expires_in
        logger.info("EdgeLite login successful, token expires in %ds", expires_in)

    async def _refresh_access_token(self) -> None:
        resp = await self._client.post(
            f"{self._base_url}/api/v1/auth/refresh",
            json={"refresh_token": self._refresh_token},
        )
        if resp.status_code != 200:
            from protoforge.core.integration.retry import AuthError
            raise AuthError(f"Token refresh failed: HTTP {resp.status_code}")
        data = resp.json()
        self._token = data.get("access_token", self._token)
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        expires_in = data.get("expires_in", 3600)
        self._token_expires = time.time() + expires_in
        logger.info("EdgeLite token refreshed")

    async def refresh_token(self) -> str:
        if self._refresh_token:
            try:
                await self._refresh_access_token()
                return self._token
            except Exception as e:
                logger.warning("Token refresh failed, falling back to login: %s", e)
        await self._login()
        return self._token

    async def close(self) -> None:
        await self._client.aclose()
