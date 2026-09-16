"""性能基准测试.

测试核心性能组件（TTLCache、ConnectionPoolManager、PerformanceMonitor、
BatchProcessor、CircuitBreaker）的正确性和性能基线。
"""

import asyncio
import time

import pytest

from protoforge.engine.performance import (
    BatchProcessor,
    CircuitBreaker,
    CircuitBreakerOpenError,
    ConnectionPoolManager,
    PerformanceMonitor,
    TTLCache,
    perf_monitor,
    ttl_cache,
)


class TestTTLCache:
    """TTLCache 单元测试."""

    @pytest.mark.asyncio
    async def test_basic_get_set(self):
        """测试基本读写操作."""
        cache = TTLCache(maxsize=10, ttl=60.0)
        await cache.set("key1", "value1")
        assert await cache.get("key1") == "value1"
        assert await cache.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_ttl_expiry(self):
        """测试 TTL 过期."""
        cache = TTLCache(maxsize=10, ttl=0.1)
        await cache.set("key1", "value1")
        assert await cache.get("key1") == "value1"
        await asyncio.sleep(0.15)
        assert await cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_maxsize_eviction(self):
        """测试达到 maxsize 后的淘汰."""
        cache = TTLCache(maxsize=3, ttl=0)
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)
        await cache.set("d", 4)  # 应淘汰最早的 "a"
        assert await cache.get("a") is None
        assert await cache.get("d") == 4

    @pytest.mark.asyncio
    async def test_invalidate(self):
        """测试手动失效."""
        cache = TTLCache(maxsize=10, ttl=0)
        await cache.set("key1", "value1")
        assert await cache.invalidate("key1") is True
        assert await cache.get("key1") is None
        assert await cache.invalidate("nonexistent") is False

    @pytest.mark.asyncio
    async def test_sync_operations(self):
        """测试同步操作."""
        cache = TTLCache(maxsize=10, ttl=60.0)
        cache.set_sync("key1", "value1")
        assert cache.get_sync("key1") == "value1"
        assert cache.get_sync("nonexistent") is None

    @pytest.mark.asyncio
    async def test_stats(self):
        """测试统计信息."""
        cache = TTLCache(maxsize=10, ttl=60.0)
        await cache.set("key1", "value1")
        await cache.get("key1")  # hit
        await cache.get("key2")  # miss
        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_clear(self):
        """测试清空缓存."""
        cache = TTLCache(maxsize=10, ttl=60.0)
        await cache.set("key1", "value1")
        await cache.clear()
        assert await cache.get("key1") is None
        assert cache.stats["size"] == 0


class TestTTLCacheDecorator:
    """ttl_cache 装饰器测试."""

    @pytest.mark.asyncio
    async def test_cache_decorator(self):
        """测试装饰器缓存功能."""
        call_count = 0

        @ttl_cache(maxsize=10, ttl=60.0)
        async def expensive_function(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = await expensive_function(5)
        result2 = await expensive_function(5)
        assert result1 == 10
        assert result2 == 10
        assert call_count == 1  # 第二次应命中缓存


class TestPerformanceMonitor:
    """PerformanceMonitor 测试."""

    def test_timer(self):
        """测试同步计时器."""
        monitor = PerformanceMonitor()
        with monitor.timer("test_op"):
            time.sleep(0.01)
        stats = monitor.get_stats("test_op")
        assert stats["count"] == 1
        assert stats["min"] > 0
        assert stats["avg"] > 0

    @pytest.mark.asyncio
    async def test_atimer(self):
        """测试异步计时器."""
        monitor = PerformanceMonitor()
        async with monitor.atimer("async_op"):
            await asyncio.sleep(0.01)
        stats = monitor.get_stats("async_op")
        assert stats["count"] == 1
        assert stats["avg"] > 0

    def test_counter(self):
        """测试计数器."""
        monitor = PerformanceMonitor()
        monitor.increment("requests")
        monitor.increment("requests", 5)
        report = monitor.get_report()
        assert report["counters"]["requests"] == 6

    def test_gauge(self):
        """测试仪表."""
        monitor = PerformanceMonitor()
        monitor.set_gauge("memory_mb", 128.5)
        report = monitor.get_report()
        assert report["gauges"]["memory_mb"] == 128.5

    def test_multiple_timers_stats(self):
        """测试多次计时的统计."""
        monitor = PerformanceMonitor()
        for i in range(10):
            with monitor.timer("batch_op"):
                time.sleep(0.001 * (i + 1))
        stats = monitor.get_stats("batch_op")
        assert stats["count"] == 10
        assert stats["min"] <= stats["avg"] <= stats["max"]
        assert stats["p50"] <= stats["p95"] <= stats["p99"]

    def test_reset(self):
        """测试重置."""
        monitor = PerformanceMonitor()
        with monitor.timer("op"):
            pass
        monitor.increment("counter")
        monitor.reset()
        report = monitor.get_report()
        assert len(report["timers"]) == 0
        assert len(report["counters"]) == 0


class TestBatchProcessor:
    """BatchProcessor 测试."""

    @pytest.mark.asyncio
    async def test_batch_flush_on_size(self):
        """测试达到 max_batch_size 时自动刷新."""
        processed_batches: list[list] = []

        async def processor(items: list) -> None:
            processed_batches.append(list(items))

        bp = BatchProcessor(processor, flush_interval=10.0, max_batch_size=3)
        await bp.add(1)
        await bp.add(2)
        await bp.add(3)  # 触发刷新
        assert len(processed_batches) == 1
        assert processed_batches[0] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_batch_flush_on_interval(self):
        """测试定时刷新."""
        processed_batches: list[list] = []

        async def processor(items: list) -> None:
            processed_batches.append(list(items))

        bp = BatchProcessor(processor, flush_interval=0.1, max_batch_size=100)
        await bp.add(1)
        await bp.add(2)
        await asyncio.sleep(0.15)
        assert len(processed_batches) == 1
        assert processed_batches[0] == [1, 2]

    @pytest.mark.asyncio
    async def test_manual_flush(self):
        """测试手动刷新."""
        processed_batches: list[list] = []

        async def processor(items: list) -> None:
            processed_batches.append(list(items))

        bp = BatchProcessor(processor, flush_interval=10.0, max_batch_size=100)
        await bp.add("a")
        await bp.add("b")
        await bp.flush()
        assert len(processed_batches) == 1
        assert processed_batches[0] == ["a", "b"]


class TestCircuitBreaker:
    """CircuitBreaker 测试."""

    @pytest.mark.asyncio
    async def test_closed_state(self):
        """测试关闭状态正常调用."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)

        async def success_func() -> str:
            return "ok"

        result = await cb.call(success_func)
        assert result == "ok"
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_open_after_failures(self):
        """测试连续失败后熔断."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)

        async def fail_func() -> None:
            raise ValueError("fail")

        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(fail_func)

        assert cb.state == "open"

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(fail_func)

    @pytest.mark.asyncio
    async def test_recovery(self):
        """测试半开状态恢复."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        call_count = 0

        async def flaky_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ValueError("fail")
            return "recovered"

        # 触发熔断
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(flaky_func)
        assert cb.state == "open"

        # 等待恢复
        await asyncio.sleep(0.15)
        assert cb.state == "half_open"

        # 半开状态下成功调用，恢复到关闭状态
        result = await cb.call(flaky_func)
        assert result == "recovered"
        assert cb.state == "closed"

    def test_reset(self):
        """测试手动重置."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)
        cb._failure_count = 5
        cb._state = "open"
        cb.reset()
        assert cb.state == "closed"
        assert cb._failure_count == 0


class TestConnectionPoolManager:
    """ConnectionPoolManager 测试."""

    @pytest.mark.asyncio
    async def test_get_client(self):
        """测试获取客户端."""
        if ConnectionPoolManager is None:
            pytest.skip("httpx not available")
        pool = ConnectionPoolManager()
        client1 = await pool.get_client("http://example.com")
        client2 = await pool.get_client("http://example.com")
        assert client1 is client2  # 同一 base_url 返回同一实例

    @pytest.mark.asyncio
    async def test_different_base_urls(self):
        """测试不同 base_url 返回不同客户端."""
        pool = ConnectionPoolManager()
        client1 = await pool.get_client("http://api1.com")
        client2 = await pool.get_client("http://api2.com")
        assert client1 is not client2

    @pytest.mark.asyncio
    async def test_close_all(self):
        """测试关闭所有客户端."""
        pool = ConnectionPoolManager()
        await pool.get_client("http://example.com")
        await pool.close_all()
        assert pool.stats["pool_count"] == 0

    @pytest.mark.asyncio
    async def test_stats(self):
        """测试统计信息."""
        pool = ConnectionPoolManager(max_connections=50, max_keepalive=10)
        await pool.get_client("http://example.com")
        stats = pool.stats
        assert stats["pool_count"] == 1
        assert stats["max_connections"] == 50
        assert "http://example.com" in stats["base_urls"]
        await pool.close_all()


class TestPerformanceBaseline:
    """性能基线测试 - 确保核心操作在可接受范围内."""

    @pytest.mark.asyncio
    async def test_cache_throughput(self):
        """缓存吞吐量基线: 10000 次操作应在 1 秒内完成."""
        cache = TTLCache(maxsize=10000, ttl=0)
        start = time.perf_counter()
        for i in range(10000):
            await cache.set(f"key_{i}", f"value_{i}")
        for i in range(10000):
            await cache.get(f"key_{i}")
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"Cache throughput too slow: {elapsed:.3f}s for 20000 ops"

    @pytest.mark.asyncio
    async def test_monitor_overhead(self):
        """监控器开销基线: 1000 次计时应在 0.5 秒内."""
        monitor = PerformanceMonitor()
        start = time.perf_counter()
        for _ in range(1000):
            with monitor.timer("baseline"):
                pass
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"Monitor overhead too high: {elapsed:.3f}s for 1000 ops"

    def test_global_monitor_exists(self):
        """测试全局监控器实例可用."""
        assert perf_monitor is not None
        report = perf_monitor.get_report()
        assert "timers" in report
        assert "counters" in report
