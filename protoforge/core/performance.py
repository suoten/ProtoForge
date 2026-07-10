"""性能优化模块.

提供缓存、连接池、异步批处理和性能监控等能力，用于提升协议仿真平台的
整体吞吐量和响应延迟。

主要组件:
    - TTLCache: 带过期时间的线程安全缓存
    - ConnectionPoolManager: HTTP/数据库连接池管理
    - BatchProcessor: 异步批处理聚合器
    - PerformanceMonitor: 性能指标采集与报告

典型用法::

    from protoforge.core.performance import ttl_cache, perf_monitor

    @ttl_cache(maxsize=128, ttl=60.0)
    async def get_device_config(device_id: str) -> dict:
        ...

    with perf_monitor.timer("modbus_read"):
        result = await server.read_points(device_id)
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import statistics
import threading
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TTLCache:
    """带 TTL (Time-To-Live) 的线程安全缓存.

    支持异步上下文中安全使用，通过 asyncio.Lock 保护并发访问。
    每个缓存条目在插入时记录过期时间，读取时自动检查并淘汰过期条目。

    :param maxsize: 最大缓存条目数，0 表示无限制
    :param ttl: 默认存活时间 (秒)，0 表示永不过期
    :param cleanup_interval: 自动清理过期条目的间隔 (秒)
    """

    def __init__(
        self,
        maxsize: int = 256,
        ttl: float = 60.0,
        cleanup_interval: float = 30.0,
    ) -> None:
        if maxsize < 0:
            raise ValueError("maxsize must be >= 0")
        if ttl < 0:
            raise ValueError("ttl must be >= 0")
        self._maxsize = maxsize
        self._ttl = ttl
        self._cleanup_interval = cleanup_interval
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()
        self._sync_lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._last_cleanup = time.monotonic()

    def _is_expired(self, expiry: float) -> bool:
        """检查条目是否过期."""
        return self._ttl > 0 and time.monotonic() > expiry

    def _cleanup_expired(self) -> int:
        """清理所有过期条目，返回清理数量."""
        now = time.monotonic()
        if now - self._last_cleanup < self._cleanup_interval:
            return 0
        self._last_cleanup = now
        expired_keys = [
            k for k, (_, expiry) in self._store.items()
            if self._is_expired(expiry)
        ]
        for k in expired_keys:
            del self._store[k]
            self._evictions += 1
        return len(expired_keys)

    def get_sync(self, key: str) -> Any | None:
        """同步获取缓存值 (线程安全)."""
        with self._sync_lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, expiry = entry
            if self._is_expired(expiry):
                del self._store[key]
                self._evictions += 1
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set_sync(self, key: str, value: Any, ttl: float | None = None) -> None:
        """同步设置缓存值 (线程安全)."""
        with self._sync_lock:
            self._cleanup_expired()
            if self._maxsize > 0 and len(self._store) >= self._maxsize:
                # 淘汰最早的条目
                oldest_key = min(self._store, key=lambda k: self._store[k][1])
                del self._store[oldest_key]
                self._evictions += 1
            effective_ttl = ttl if ttl is not None else self._ttl
            expiry = time.monotonic() + effective_ttl if effective_ttl > 0 else float("inf")
            self._store[key] = (value, expiry)

    async def get(self, key: str) -> Any | None:
        """异步获取缓存值."""
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, expiry = entry
            if self._is_expired(expiry):
                del self._store[key]
                self._evictions += 1
                self._misses += 1
                return None
            self._hits += 1
            return value

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """异步设置缓存值."""
        async with self._lock:
            self._cleanup_expired()
            if self._maxsize > 0 and len(self._store) >= self._maxsize:
                oldest_key = min(self._store, key=lambda k: self._store[k][1])
                del self._store[oldest_key]
                self._evictions += 1
            effective_ttl = ttl if ttl is not None else self._ttl
            expiry = time.monotonic() + effective_ttl if effective_ttl > 0 else float("inf")
            self._store[key] = (value, expiry)

    async def invalidate(self, key: str) -> bool:
        """使指定 key 的缓存失效，返回是否成功删除."""
        async with self._lock:
            return self._store.pop(key, None) is not None

    async def clear(self) -> None:
        """清空整个缓存."""
        async with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    @property
    def stats(self) -> dict[str, Any]:
        """返回缓存统计信息."""
        total = self._hits + self._misses
        return {
            "size": len(self._store),
            "maxsize": self._maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "hit_rate": self._hits / total if total > 0 else 0.0,
        }


def ttl_cache(
    maxsize: int = 128,
    ttl: float = 60.0,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """异步函数 TTL 缓存装饰器.

    使用 TTLCache 缓存异步函数的返回值，基于参数生成缓存 key。

    :param maxsize: 最大缓存条目数
    :param ttl: 缓存存活时间 (秒)
    :return: 装饰器函数

    用法::

        @ttl_cache(maxsize=64, ttl=30.0)
        async def fetch_device(device_id: str) -> dict:
            ...
    """
    cache = TTLCache(maxsize=maxsize, ttl=ttl)

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            # 生成缓存 key
            key_parts = [repr(args), repr(sorted(kwargs.items()))]
            key = hashlib.md5("|".join(key_parts).encode()).hexdigest()
            cached = await cache.get(key)
            if cached is not None:
                return cached
            result = await func(*args, **kwargs)
            await cache.set(key, result)
            return result
        wrapper._cache = cache  # type: ignore[attr-defined]
        return wrapper

    return decorator


class ConnectionPoolManager:
    """HTTP/TCP 连接池管理器.

    管理 httpx.AsyncClient 实例池，复用 TCP 连接，减少握手开销。
    支持按 base_url 分组，每个 base_url 对应一个独立的连接池。

    :param max_connections: 每个 base_url 的最大连接数
    :param max_keepalive: 每个 base_url 的最大保活连接数
    :param keepalive_expiry: 保活连接过期时间 (秒)
    """

    def __init__(
        self,
        max_connections: int = 100,
        max_keepalive: int = 20,
        keepalive_expiry: float = 30.0,
    ) -> None:
        self._max_connections = max_connections
        self._max_keepalive = max_keepalive
        self._keepalive_expiry = keepalive_expiry
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()

    async def get_client(self, base_url: str = "") -> httpx.AsyncClient:
        """获取或创建指定 base_url 的 HTTP 客户端."""
        async with self._lock:
            client = self._clients.get(base_url)
            if client is None or client.is_closed:
                client = httpx.AsyncClient(
                    base_url=base_url or None,
                    limits=httpx.Limits(
                        max_connections=self._max_connections,
                        max_keepalive_connections=self._max_keepalive,
                        keepalive_expiry=self._keepalive_expiry,
                    ),
                    timeout=httpx.Timeout(30.0),
                )
                self._clients[base_url] = client
            return client

    async def close_all(self) -> None:
        """关闭所有连接池中的客户端."""
        async with self._lock:
            for url, client in self._clients.items():
                try:
                    await client.aclose()
                except Exception as e:
                    logger.warning("Error closing HTTP client for %s: %s", url, e)
            self._clients.clear()

    @property
    def stats(self) -> dict[str, Any]:
        """返回连接池统计信息."""
        return {
            "pool_count": len(self._clients),
            "max_connections": self._max_connections,
            "max_keepalive": self._max_keepalive,
            "base_urls": list(self._clients.keys()),
        }


# 全局连接池管理器实例
_pool_manager: ConnectionPoolManager | None = None
_pool_lock = threading.Lock()


def get_connection_pool() -> ConnectionPoolManager:
    """获取全局连接池管理器单例."""
    global _pool_manager
    if _pool_manager is None:
        with _pool_lock:
            if _pool_manager is None:
                _pool_manager = ConnectionPoolManager()
    return _pool_manager


@dataclass
class MetricEntry:
    """单个性能指标记录."""

    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    tags: dict[str, str] = field(default_factory=dict)


class PerformanceMonitor:
    """性能监控采集器.

    采集函数执行时间、内存使用等性能指标，支持定时报告和阈值告警。

    用法::

        monitor = PerformanceMonitor()

        with monitor.timer("modbus_read"):
            await server.read_points(device_id)

        report = monitor.get_report()
    """

    def __init__(self, window_size: int = 1000) -> None:
        self._timers: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=window_size))
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}
        self._lock = threading.Lock()

    @contextmanager
    def timer(self, name: str, tags: dict[str, str] | None = None):
        """同步计时上下文管理器."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - start) * 1000  # ms
            with self._lock:
                self._timers[name].append(elapsed)
                self._counters[f"{name}_count"] += 1

    @asynccontextmanager
    async def atimer(self, name: str, tags: dict[str, str] | None = None):
        """异步计时上下文管理器."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - start) * 1000  # ms
            with self._lock:
                self._timers[name].append(elapsed)
                self._counters[f"{name}_count"] += 1

    def increment(self, name: str, value: int = 1) -> None:
        """递增计数器."""
        with self._lock:
            self._counters[name] += value

    def set_gauge(self, name: str, value: float) -> None:
        """设置仪表值."""
        with self._lock:
            self._gauges[name] = value

    def get_stats(self, name: str) -> dict[str, float]:
        """获取指定计时器的统计信息."""
        with self._lock:
            values = list(self._timers.get(name, []))
        if not values:
            return {"count": 0, "min": 0, "max": 0, "avg": 0, "p50": 0, "p95": 0, "p99": 0}
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        return {
            "count": n,
            "min": sorted_vals[0],
            "max": sorted_vals[-1],
            "avg": statistics.mean(sorted_vals),
            "p50": sorted_vals[n // 2],
            "p95": sorted_vals[int(n * 0.95)] if n > 1 else sorted_vals[0],
            "p99": sorted_vals[int(n * 0.99)] if n > 1 else sorted_vals[0],
        }

    def get_report(self) -> dict[str, Any]:
        """生成完整性能报告."""
        with self._lock:
            timer_stats = {name: self.get_stats(name) for name in self._timers}
            return {
                "timers": timer_stats,
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "timestamp": time.time(),
            }

    def reset(self) -> None:
        """重置所有指标."""
        with self._lock:
            self._timers.clear()
            self._counters.clear()
            self._gauges.clear()


# 全局性能监控器
perf_monitor = PerformanceMonitor()


class BatchProcessor:
    """异步批处理聚合器.

    将高频小请求聚合成批量操作，减少 I/O 次数。
    适用于数据库写入、API 调用等场景。

    :param flush_interval: 自动刷新间隔 (秒)
    :param max_batch_size: 最大批量大小，达到后自动刷新
    :param processor: 批量处理回调函数
    """

    def __init__(
        self,
        processor: Callable[[list[Any]], Awaitable[Any]],
        flush_interval: float = 1.0,
        max_batch_size: int = 100,
    ) -> None:
        self._processor = processor
        self._flush_interval = flush_interval
        self._max_batch_size = max_batch_size
        self._batch: list[Any] = []
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._running = False

    async def add(self, item: Any) -> None:
        """添加一个条目到批处理队列."""
        async with self._lock:
            self._batch.append(item)
            if len(self._batch) >= self._max_batch_size:
                await self._flush()
            elif not self._running:
                self._running = True
                self._flush_task = asyncio.create_task(self._scheduled_flush())

    async def _scheduled_flush(self) -> None:
        """定时刷新."""
        await asyncio.sleep(self._flush_interval)
        async with self._lock:
            self._running = False
            if self._batch:
                await self._flush()

    async def _flush(self) -> None:
        """执行批量处理."""
        if not self._batch:
            return
        batch = self._batch
        self._batch = []
        try:
            await self._processor(batch)
        except Exception as e:
            logger.error("Batch processor error: %s", e)

    async def flush(self) -> None:
        """手动触发刷新."""
        async with self._lock:
            self._running = False
            if self._flush_task:
                self._flush_task.cancel()
                self._flush_task = None
            await self._flush()

    async def stop(self) -> None:
        """停止批处理器并刷新剩余数据."""
        await self.flush()


class CircuitBreaker:
    """熔断器模式.

    在连续失败达到阈值时断开电路，阻止后续请求，
    经过冷却期后进入半开状态，尝试恢复。

    :param failure_threshold: 连续失败阈值
    :param recovery_timeout: 恢复超时时间 (秒)
    :param expected_exception: 预期的异常类型
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        expected_exception: type[Exception] = Exception,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._expected_exception = expected_exception
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._state = "closed"  # closed, open, half_open
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        """当前熔断器状态."""
        if self._state == "open":
            if self._last_failure_time and \
                    time.monotonic() - self._last_failure_time > self._recovery_timeout:
                self._state = "half_open"
        return self._state

    async def call(self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        """通过熔断器执行异步函数."""
        async with self._lock:
            if self.state == "open":
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is open (failures={self._failure_count})"
                )

        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                if self._state == "half_open":
                    self._state = "closed"
                    self._failure_count = 0
            return result
        except self._expected_exception:
            async with self._lock:
                self._failure_count += 1
                self._last_failure_time = time.monotonic()
                if self._failure_count >= self._failure_threshold:
                    self._state = "open"
                    logger.warning(
                        "Circuit breaker opened after %d failures",
                        self._failure_count,
                    )
            raise

    def reset(self) -> None:
        """重置熔断器到关闭状态."""
        self._state = "closed"
        self._failure_count = 0
        self._last_failure_time = None


class CircuitBreakerOpenError(Exception):
    """熔断器处于打开状态时抛出的异常."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


# 向后兼容: 确保 httpx 可用
try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]
    logger.warning("httpx not installed, ConnectionPoolManager will be unavailable")


__all__ = [
    "TTLCache",
    "ttl_cache",
    "ConnectionPoolManager",
    "get_connection_pool",
    "PerformanceMonitor",
    "perf_monitor",
    "BatchProcessor",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "MetricEntry",
]
