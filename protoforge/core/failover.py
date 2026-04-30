import asyncio
import contextlib
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)


class FailoverManager:
    def __init__(self):
        self._primary_url: str | None = None
        self._standby_url: str | None = None
        self._is_primary = True
        self._health_check_interval = int(os.environ.get("PROTOFORGE_FAILOVER_INTERVAL", "10"))
        self._health_check_task: asyncio.Task | None = None
        self._on_failover_callbacks = []
        self._on_recovery_callbacks = []
        self._failover_count = 0
        self._last_failover_time: float | None = None
        self._status = "primary"

    def configure(
        self,
        primary_url: str,
        standby_url: str = "",
        is_primary: bool = True,
    ) -> None:
        self._primary_url = primary_url
        self._standby_url = standby_url
        self._is_primary = is_primary
        self._status = "primary" if is_primary else "standby"
        logger.info("Failover configured: role=%s, primary=%s, standby=%s",
                     self._status, primary_url, standby_url)

    def on_failover(self, callback) -> None:
        self._on_failover_callbacks.append(callback)

    def on_recovery(self, callback) -> None:
        self._on_recovery_callbacks.append(callback)

    async def start(self) -> None:
        if not self._standby_url:
            logger.debug("No standby URL configured, failover monitoring disabled")
            return
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info("Failover health monitoring started (interval=%ds)", self._health_check_interval)

    async def stop(self) -> None:
        if self._health_check_task:
            self._health_check_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_check_task
        logger.info("Failover manager stopped")

    async def _health_check_loop(self) -> None:
        consecutive_failures = 0
        max_failures = 3
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                if self._is_primary:
                    healthy = await self._check_peer_health(self._standby_url)
                    if not healthy:
                        logger.debug("Standby peer %s is not reachable", self._standby_url)
                else:
                    primary_healthy = await self._check_peer_health(self._primary_url)
                    if not primary_healthy:
                        consecutive_failures += 1
                        if consecutive_failures >= max_failures:
                            await self._promote_to_primary()
                            consecutive_failures = 0
                    else:
                        consecutive_failures = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Failover health check error: %s", e)

    async def _check_peer_health(self, url: str) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{url}/health")
                return resp.status_code == 200
        except Exception as e:
            logger.debug("Health check failed for %s: %s", url, e)
            return False

    async def _promote_to_primary(self) -> None:
        logger.warning("Primary peer unreachable, promoting to primary")
        self._is_primary = True
        self._status = "primary"
        self._failover_count += 1
        self._last_failover_time = time.time()
        for callback in self._on_failover_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error("Failover callback error: %s", e)

    async def demote_to_standby(self) -> None:
        logger.info("Demoting to standby (primary recovered)")
        self._is_primary = False
        self._status = "standby"
        for callback in self._on_recovery_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error("Recovery callback error: %s", e)

    def get_status(self) -> dict[str, Any]:
        return {
            "role": self._status,
            "is_primary": self._is_primary,
            "primary_url": self._primary_url,
            "standby_url": self._standby_url,
            "failover_count": self._failover_count,
            "last_failover_time": self._last_failover_time,
            "health_check_interval": self._health_check_interval,
        }


failover_manager = FailoverManager()
