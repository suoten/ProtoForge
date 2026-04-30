import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class IntegrationError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class NetworkError(IntegrationError):
    def __init__(self, message: str):
        super().__init__(message, retryable=True)


class AuthError(IntegrationError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class ValidationError(IntegrationError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class ServerError(IntegrationError):
    def __init__(self, message: str):
        super().__init__(message, retryable=True)


class RetryPolicy:
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
        max_total_time: float = 120.0,
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.max_total_time = max_total_time
        self._attempt = 0
        self._last_error: Exception | None = None

    @property
    def attempt(self) -> int:
        return self._attempt

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    def get_delay(self) -> float:
        delay = self.initial_delay * (self.backoff_factor ** self._attempt)
        return min(delay, self.max_delay)

    def should_retry(self, error: Exception) -> bool:
        self._last_error = error
        if isinstance(error, IntegrationError) and not error.retryable:
            return False
        return not self._attempt >= self.max_retries

    async def wait(self) -> None:
        delay = self.get_delay()
        logger.info("Retry attempt %d/%d, waiting %.1fs", self._attempt + 1, self.max_retries, delay)
        await asyncio.sleep(delay)
        self._attempt += 1

    def reset(self) -> None:
        self._attempt = 0
        self._last_error = None

    async def execute(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        self.reset()
        start_time = time.monotonic()
        while True:
            try:
                result = await func(*args, **kwargs)
                self.reset()
                return result
            except Exception as e:
                if not self.should_retry(e):
                    raise
                elapsed = time.monotonic() - start_time
                if elapsed >= self.max_total_time:
                    logger.warning("RetryPolicy.execute exceeded max_total_time (%.1fs), giving up", self.max_total_time)
                    raise
                await self.wait()
