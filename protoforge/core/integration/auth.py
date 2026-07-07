import asyncio
import logging
import time

import httpx

from protoforge.core.defaults import HTTP_TIMEOUT_DEFAULT

logger = logging.getLogger(__name__)


class IntegrationAuth:
    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        refresh_margin: float = 30.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._refresh_margin = refresh_margin
        self._token: str = ""
        self._refresh_token: str = ""
        self._csrf_token: str = ""  # EdgeLite CSRF token
        self._token_expires: float = 0.0
        self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_DEFAULT)
        self._lock = asyncio.Lock()  # 防止并发刷新 Token

    @property
    def token(self) -> str:
        return self._token

    @property
    def csrf_token(self) -> str:
        return self._csrf_token

    @property
    def is_authenticated(self) -> bool:
        return bool(self._token) and time.time() < self._token_expires - self._refresh_margin

    async def ensure_token(self) -> str:
        if self.is_authenticated:
            return self._token
        async with self._lock:
            # 双重检查：获取锁后再次检查，避免重复刷新
            if self.is_authenticated:
                return self._token
            if self._refresh_token:
                try:
                    await self._refresh_access_token()
                    return self._token
                except Exception as e:
                    logger.warning("Token refresh failed, falling back to login: %s", e)
            await self._login()
            return self._token

    async def _login(self) -> None:
        try:
            # FIXED-P0: 使用 post() 替代 stream()，避免 "streaming response content" 错误
            resp = await self._client.post(
                f"{self._base_url}/api/v1/auth/login",
                json={"username": self._username, "password": self._password},
            )
            if resp.status_code != 200:
                from protoforge.core.integration.retry import AuthError
                raise AuthError(f"Login failed: HTTP {resp.status_code}")
            data = resp.json()
        except httpx.ConnectError as e:
            from protoforge.core.integration.retry import NetworkError
            raise NetworkError(f"Connection failed: {e}") from e
        except httpx.TimeoutException as e:
            from protoforge.core.integration.retry import NetworkError
            raise NetworkError(f"Login timeout: {e}") from e
        token_data = data.get("data", data)
        if isinstance(token_data, dict):
            self._token = token_data.get("access_token", "")
            self._refresh_token = token_data.get("refresh_token", "")
            self._csrf_token = token_data.get("csrf_token", "")
            expires_in = token_data.get("expires_in", 3600)
        else:
            self._token = data.get("access_token", "")
            self._refresh_token = data.get("refresh_token", "")
            self._csrf_token = data.get("csrf_token", "")
            expires_in = data.get("expires_in", 3600)
        self._token_expires = time.time() + expires_in
        logger.info("EdgeLite login successful, token expires in %ds", expires_in)

        # FIXED-P0: EdgeLite 初始管理员账户 may have must_change_password=True,
        # 导致除 change-password/me/logout 外所有端点返回 403。
        # 登录后立即检查并自动修改密码（使用当前密码作为新密码），
        # 以解除 must_change_password 限制。
        await self._handle_must_change_password()

    async def _handle_must_change_password(self) -> None:
        """检测 EdgeLite 的 must_change_password 限制并自动解除。

        EdgeLite 初始管理员账户 may have must_change_password=True，
        导致除 change-password/me/logout 外所有端点返回 403。
        此方法通过 GET /api/v1/auth/me 检测该标志，
        如果为 True 则自动调用 change-password 端点解除限制。
        """
        if not self._token:
            return
        try:
            # 检查当前用户状态
            headers = {"Authorization": f"Bearer {self._token}"}
            if self._csrf_token:
                headers["X-CSRF-Token"] = self._csrf_token
            me_resp = await self._client.get(
                f"{self._base_url}/api/v1/auth/me",
                headers=headers,
            )
            if me_resp.status_code != 200:
                logger.debug("Failed to check user status after login: HTTP %d", me_resp.status_code)
                return

            me_data = me_resp.json()
            user_data = me_data.get("data", me_data)
            if not isinstance(user_data, dict):
                return

            must_change = user_data.get("must_change_password", False)
            if not must_change:
                return

            logger.info("EdgeLite user has must_change_password=True, auto-changing password to unlock API access")

            # EdgeLite change-password 端点要求新密码不能与旧密码相同，
            # 所以我们在原密码后追加 "!1" 作为新密码
            new_password = self._password + "!1"
            change_headers = {"Authorization": f"Bearer {self._token}"}
            if self._csrf_token:
                change_headers["X-CSRF-Token"] = self._csrf_token
            # EdgeLite change-password 使用 Body(..., embed=True) 格式
            change_resp = await self._client.post(
                f"{self._base_url}/api/v1/auth/change-password",
                json={
                    "old_password": self._password,
                    "new_password": new_password,
                },
                headers=change_headers,
            )
            if change_resp.status_code in (200, 204):
                logger.info("EdgeLite must_change_password flag cleared successfully")
                # 更新本地密码为新密码，以便后续 refresh 使用
                self._password = new_password
                # change-password 后 token 可能失效，需要重新登录
                self._token = ""
                self._refresh_token = ""
                self._csrf_token = ""
                self._token_expires = 0.0
                await self._login_once()
            else:
                try:
                    err_detail = change_resp.text[:300]
                except Exception:
                    err_detail = ""
                logger.warning(
                    "EdgeLite change-password failed: HTTP %d (%s), API access may be restricted",
                    change_resp.status_code, err_detail,
                )
        except Exception as e:
            logger.warning("Error handling must_change_password: %s", e)

    async def _login_once(self) -> None:
        """单次登录（不触发 must_change_password 检查，防止递归）。"""
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/auth/login",
                json={"username": self._username, "password": self._password},
            )
            if resp.status_code != 200:
                from protoforge.core.integration.retry import AuthError
                raise AuthError(f"Login failed: HTTP {resp.status_code}")
            data = resp.json()
        except httpx.ConnectError as e:
            from protoforge.core.integration.retry import NetworkError
            raise NetworkError(f"Connection failed: {e}") from e
        except httpx.TimeoutException as e:
            from protoforge.core.integration.retry import NetworkError
            raise NetworkError(f"Login timeout: {e}") from e
        token_data = data.get("data", data)
        if isinstance(token_data, dict):
            self._token = token_data.get("access_token", "")
            self._refresh_token = token_data.get("refresh_token", "")
            self._csrf_token = token_data.get("csrf_token", "")
            expires_in = token_data.get("expires_in", 3600)
        else:
            self._token = data.get("access_token", "")
            self._refresh_token = data.get("refresh_token", "")
            self._csrf_token = data.get("csrf_token", "")
            expires_in = data.get("expires_in", 3600)
        self._token_expires = time.time() + expires_in
        logger.info("EdgeLite re-login successful after password change, token expires in %ds", expires_in)

    async def _refresh_access_token(self) -> None:
        resp = await self._client.post(
            f"{self._base_url}/api/v1/auth/refresh",
            json={"refresh": self._refresh_token},
        )
        if resp.status_code != 200:
            from protoforge.core.integration.retry import AuthError
            raise AuthError(f"Token refresh failed: HTTP {resp.status_code}")
        data = resp.json()
        token_data = data.get("data", data)
        if isinstance(token_data, dict):
            self._token = token_data.get("access_token", self._token)
            self._refresh_token = token_data.get("refresh_token", self._refresh_token)
            new_csrf = token_data.get("csrf_token", "")
            if new_csrf:
                self._csrf_token = new_csrf
            expires_in = token_data.get("expires_in", 3600)
        else:
            self._token = data.get("access_token", self._token)
            self._refresh_token = data.get("refresh_token", self._refresh_token)
            new_csrf = data.get("csrf_token", "")
            if new_csrf:
                self._csrf_token = new_csrf
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
