import time
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse


class RateLimiter:
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._requests: dict[str, list[float]] = {}

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        window_start = now - self._window_seconds

        if key not in self._requests:
            self._requests[key] = []

        self._requests[key] = [t for t in self._requests[key] if t > window_start]

        if len(self._requests[key]) >= self._max_requests:
            return False

        self._requests[key].append(now)
        return True

    def get_remaining(self, key: str) -> int:
        now = time.time()
        window_start = now - self._window_seconds
        if key not in self._requests:
            return self._max_requests
        self._requests[key] = [t for t in self._requests[key] if t > window_start]
        return max(0, self._max_requests - len(self._requests[key]))

    def get_retry_after(self, key: str) -> int:
        if key not in self._requests or not self._requests[key]:
            return 0
        oldest = min(self._requests[key])
        retry = int(oldest + self._window_seconds - time.time()) + 1
        return max(0, retry)


_default_limiter = RateLimiter(max_requests=100, window_seconds=60)
_auth_limiter = RateLimiter(max_requests=10, window_seconds=60)


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    client_ip = get_client_ip(request)

    if path.startswith("/api/v1/auth/login"):
        limiter = _auth_limiter
        key = f"auth:{client_ip}"
    else:
        limiter = _default_limiter
        key = f"api:{client_ip}:{path}"

    if not limiter.is_allowed(key):
        retry_after = limiter.get_retry_after(key)
        return JSONResponse(
            status_code=429,
            content={
                "code": 429,
                "message": "请求过于频繁，请稍后再试",
                "data": None,
                "retry_after": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limiter._max_requests)
    response.headers["X-RateLimit-Remaining"] = str(limiter.get_remaining(key))
    return response
